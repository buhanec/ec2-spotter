#!/usr/bin/env python3

"""Initialise spot request"""

import base64

import boto3
from botocore.credentials import Credentials

ec2 = boto3.resource('ec2')

CREDENTIALS = boto3.DEFAULT_SESSION.get_credentials()  # type: Credentials

ZONE_ID = 'eu-central-1b'
VOLUME_ID = 'vol-05bf2a4905dfcba08'
VOLUME_NAME = 'new-mc'
EIP_ID = 'eipalloc-cf4f45e1'
SECURITY_GROUP_ID = 'sg-5a5fdc31'
PRE_BOOT_AMI = 'ami-c7e0c82c'

KEY_NAME = 'Alen new'

INSTANCE_TYPE = 'c5.xlarge'
INSTANCE_BID = 0.10

USER_DATA = f'''#!/usr/bin/env bash

cd /root

mkdir -p .aws
echo '[default]' > .aws/credentials
echo 'aws_access_key_id = {CREDENTIALS.access_key}' > .aws/credentials
echo 'aws_secret_access_key = {CREDENTIALS.secret_key}' > .aws/credentials

export TERM="linux"

apt-get update 
apt-get install -y wget python3 python3-requests python3-psutil python3-boto3

wget https://raw.githubusercontent.com/buhanec/ec2-spotter/master/bootstrap.py

./bootstrap.py {VOLUME_NAME} {EIP_ID}
'''

ec2.request_spot_instances(ImageId=PRE_BOOT_AMI,
                           InstanceType=INSTANCE_TYPE,
                           KeyName=KEY_NAME,
                           EbsOptimized=True,
                           Placement={'AvailabilityZone': ZONE_ID},
                           BlockDeviceMappings=[{
                               'DeviceName': '/dev/sda1',
                               'Ebs': {
                                   'DeleteOnTermination': True,
                                   'VolumeType': 'gp2',
                                   'VolumeSize': 8
                               }
                           }],
                           NetworkInterfaces=[{
                               'DeviceIndex': 0,
                               'SubnetId': '',
                               'Groups': [SECURITY_GROUP_ID],
                               'AssociatePublicIpAddress': False
                           }],
                           UserData=base64.b64encode(USER_DATA))
