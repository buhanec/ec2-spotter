#!/usr/bin/env python3

"""Remount root drive"""

import os
import subprocess
import sys
import time
import uuid

import boto3
import psutil
import requests

INSTANCE_URL = 'http://169.254.169.254/latest/meta-data/instance-id'
ZONE_URL = 'http://169.254.169.254/latest/meta-data/placement/availability-zone'

instance_id = requests.get(INSTANCE_URL).text
zone_id = requests.get(ZONE_URL).text
region_name = instance_id[:-1]
volume_name = sys.argv[1]

ec2 = boto3.resource('ec2', region_name=region_name)

# Allocate IP
try:
    response = ec2.associate_address(AllocationId=sys.argv[2],
                                     InstanceId=instance_id)
except IndexError:
    pass

# Find Volume
filters = [{'Name': 'tag-key', 'Values': ['Name']},
           {'Name': 'tag-value', 'Values': [volume_name]}]
volumes = ec2.describe_volumes(Filters=filters, Region=region_name)
for volume in volumes['Volumes']:
    if volume['State'] == 'available':
        volume_id = volume['VolumeId']
        move_volume = volume['AvailabilityZone'] != zone_id
        break
else:
    print(f'Could not find volume {volume_name!r}')
    sys.exit(1)

# Move between availability zones
if move_volume:
    print('Moving snapshot')
    # Create snapshot of current volume
    snapshot_id = ec2.create_snapshot(VolumeId=volume_id).snapshot_id
    while True:
        filters = [{'Name': 'tag-key', 'Values': ['State']},
                   {'Name': 'tag-value', 'Values': ['completed']}]
        snapshots = ec2.describe_snapshots(SnapshotIds=[snapshot_id])
        if snapshots['Snapshots']:
            break
        print('Waiting 10s before checking if snapshot completed...')
        time.sleep(10)

    # Create new volume
    new_volume_id = ec2.create_volume(AvailabilityZone=zone_id,
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
                                      ])['VolumeId']
    while True:
        filters = [{'Name': 'tag-key', 'Values': ['State']},
                   {'Name': 'tag-value', 'Values': ['available']}]
        volumes = ec2.describe_volumes(VolumeIds=[new_volume_id],
                                       Filters=filters)
        if volumes['Volumes']:
            break
        print('Waiting 10s before checking if volume available...')
        time.sleep(10)

    # Remove old snapshot and volume
    ec2.delete_volume(VolumeId=volume_id)
    ec2.delete_snapshot(SnapshotId=snapshot_id)

    # New volume is now the volume
    volume_id = new_volume_id

# Attach volume
device = '/dev/xvdf1'
ec2.attach_volume(Device=device[:-1],
                  InstanceId=instance_id,
                  VolumeId=volume_id)
while not [d for d in psutil.disk_partitions() if d.device == device]:
    print('Waiting 10s for volume to attach...')
    time.sleep(10)

# Clean up credentials
os.unlink('$HOME/.aws/credentials')

# Ready for the swap
subprocess.run(('tune2fs', device, '-U', uuid.uuid4()))

# Load up new /sbin/init
os.remove('/sbin/init')
with open('/sbin/init') as f:
    f.write(f'''#!/usr/bin/env bash

mount {device} /swapped
cd /swapped
mkdir old
pivot_root . old

for dir in /dev /proc /sys /run; do
    mount --move old/${{dir}} ${{dir}}
done

exec chroot . /sbin/init 
''')

os.chmod('/sbin/init', 777)

subprocess.run(('shutdown', '-r', 'now'))
