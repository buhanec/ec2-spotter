#!/usr/bin/env python3

"""Remount root drive"""

import os
import subprocess
import sys
import time
import uuid

import boto3
import requests

INSTANCE_URL = 'http://169.254.169.254/latest/meta-data/instance-id'
INSTANCE_TYPE = 'http://169.254.169.254/latest/meta-data/instance-type'
ZONE_URL = 'http://169.254.169.254/latest/meta-data/placement/availability-zone'

instance_id = requests.get(INSTANCE_URL).text
zone_id = requests.get(ZONE_URL).text
region_name = zone_id[:-1]
volume_name = sys.argv[1]

ec2 = boto3.client('ec2', region_name=region_name)

# Allocate IP
print('[0] Allocating IP')
try:
    response = ec2.associate_address(AllocationId=sys.argv[2],
                                     InstanceId=instance_id,
                                     AllowReassociation=True)
    print('    ... allocated')
except IndexError:
    print('    ... no need to allocate')

# Find Volume
print('[1] Finding volume')
volume = None
move_volume = False
while volume is None:
    filters = [{'Name': 'tag-key', 'Values': ['Name']},
               {'Name': 'tag-value', 'Values': [volume_name]}]
    volumes = ec2.describe_volumes(Filters=filters)  # TODO: handle x-region

    if not len(volumes['Volumes']):
        print('    ... no volumes with name', repr(volume_name))
        sys.exit(1)

    for volume in volumes['Volumes']:
        if volume['State'] == 'available':
            break

    if volume is None:
      print('    ... all volumes with name', repr(volume_name), 'in use')
      time.sleep(10)
print('    ... found volume with name', repr(volume_name), 'to be', repr(volume['VolumeId']))

# Move between availability zones
print('[2] Moving availability zones')
if volume['AvailabilityZone'] != zone_id:
    print('    ... moving snapshot from', repr(volume['AvailabilityZone']), 'to', repr(zone_id))
    # Create snapshot of current volume
    snapshot_id = ec2.create_snapshot(VolumeId=volume['VolumeId']).snapshot_id
    while True:
        filters = [{'Name': 'tag-key', 'Values': ['State']},
                   {'Name': 'tag-value', 'Values': ['completed']}]
        snapshots = ec2.describe_snapshots(SnapshotIds=[snapshot_id])
        if snapshots['Snapshots']:
            break
        print('    ... waiting for snapshop')
        time.sleep(10)

    # Create new volume
    new_volume = ec2.create_volume(AvailabilityZone=zone_id,
                                   Encrypted=volume['Encrypted'],
                                   Iops=volume['Iops'],
                                   KmsKeyId=volume['KmsKeyId'],
                                   Size=volume['Size'],
                                   SnapshotId=snapshot_id,
                                   VolumeType=volume['VolumeType'],
                                   TagSpecifications=[
                                       {
                                           'ResourceType': 'volume',
                                           'Tags': volume['Tags']
                                       },
                                   ])
    while True:
        filters = [{'Name': 'tag-key', 'Values': ['State']},
                   {'Name': 'tag-value', 'Values': ['available']}]
        volumes = ec2.describe_volumes(VolumeIds=[new_volume['VolumeId']],
                                       Filters=filters)
        if volumes['Volumes']:
            break
        print('    ... waiting for volume')
        time.sleep(10)
    # Remove old snapshot and volume
    # ec2.delete_volume(VolumeId=volume_id)
    # ec2.delete_snapshot(SnapshotId=snapshot_id)

    # New volume is now the volume
    volume = new_volume
print('    ... done')

# Attach volume
print('[3] Attaching volume')
ec2.attach_volume(Device='/dev/sdf',
                  InstanceId=instance_id,
                  VolumeId=volume['VolumeId'])
while not ec2.describe_volumes(VolumeIds=[volume['VolumeId']])['Volumes'][0]['State'] == 'in-use':
    print('    ... waiting')
    time.sleep(10)
time.sleep(10)
print('    ... done')


# FUCK SHIT UP
print('[4] Preparing volume')
instance_gen = int(requests.get(INSTANCE_TYPE).text[1])
device = '/dev/nvme1n1p1' if instance_gen == 5 else '/dev/xvdf1'
print('    ... instance gen', instance_gen, 'has device', device)
subprocess.run(('e2fsck', device, '-y'))
subprocess.run(('tune2fs', device, '-U', str(uuid.uuid4())))
print('    ... done')

# Load up new /sbin/init
print('[5] Rewriting /sbin/init')
os.unlink('/sbin/init')
with open('/sbin/init', 'w') as f:
    f.write('''#!/usr/bin/env bash

mkdir -p /swapped
mount {device} /swapped
mkdir -p /swapped/old

pivot_root /swapped /swapped/old

for dir in /dev /proc /sys /run; do
    mount --move old/$dir $dir
done

exec chroot . /sbin/init
'''.format(**globals()))  # bring me home to 3.6+

os.chmod('/sbin/init', 777)

# Clean up credentials
# os.unlink('/root/.aws/credentials')

# subprocess.run(('shutdown', '-r', 'now'))
