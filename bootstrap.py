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
try:
    response = ec2.associate_address(AllocationId=sys.argv[2],
                                     InstanceId=instance_id,
                                     AllowReassociation=True)
except IndexError:
    pass

# Find Volume
volume = None
move_volume = False
while volume is None:
    filters = [{'Name': 'tag-key', 'Values': ['Name']},
               {'Name': 'tag-value', 'Values': [volume_name]}]
    volumes = ec2.describe_volumes(Filters=filters)  # TODO: handle x-region

    if not len(volumes['Volumes']):
        print('Could not find any volumes for ' + repr(volume_name))
        sys.exit(1)

    for volume in volumes['Volumes']:
        if volume['State'] == 'available':
            break

    print('Waiting 10s, all volumes with name', repr(volume_name), 'in use...')
    time.sleep(10)

# Move between availability zones
if volume['AvailabilityZone'] != zone_id:
    print('Moving snapshot')
    # Create snapshot of current volume
    snapshot_id = ec2.create_snapshot(VolumeId=volume['VolumeId']).snapshot_id
    while True:
        filters = [{'Name': 'tag-key', 'Values': ['State']},
                   {'Name': 'tag-value', 'Values': ['completed']}]
        snapshots = ec2.describe_snapshots(SnapshotIds=[snapshot_id])
        if snapshots['Snapshots']:
            break
        print('Waiting 10s before checking if snapshot completed...')
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
        print('Waiting 10s before checking if volume available...')
        time.sleep(10)

    # Remove old snapshot and volume
    # ec2.delete_volume(VolumeId=volume_id)
    # ec2.delete_snapshot(SnapshotId=snapshot_id)

    # New volume is now the volume
    volume = new_volume

# Attach volume
ec2.attach_volume(Device='/dev/sdf',
                  InstanceId=instance_id,
                  VolumeId=volume['VolumeId'])
while not ec2.describe_volumes(VolumeIds=[volume['VolumeId']])['Volumes'][0]['State'] == 'in-use':
    print('Waiting 10s for volume to be in use...')
    time.sleep(10)
time.sleep(5)

# Clean up credentials
os.unlink(os.path.expandvars('$HOME/.aws/credentials'))

# FUCK SHIT UP
instance_gen = int(requests.get(INSTANCE_TYPE).text[1])

device = '/dev/nvme1n1p1' if instance_gen == 5 else '/dev/xvdf1'

# Ready for the swap
subprocess.run(('e2fsck', device, '-y'))
subprocess.run(('tune2fs', device, '-U', str(uuid.uuid4())))

# Load up new /sbin/init
# os.remove('/sbin/init')
with open('/root/init', 'w') as f:
    f.write('''#!/usr/bin/env bash

mount {device} /swapped
cd /swapped
mkdir old
pivot_root . old

for dir in /dev /proc /sys /run; do
    mount --move old/$dir $dir
done

exec chroot . /sbin/init'''.format(**globals()))  # bring me home to 3.6+

# os.chmod('/sbin/init', 777)

# subprocess.run(('shutdown', '-r', 'now'))
