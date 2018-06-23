#!/usr/bin/env python3

"""Initialise spot request"""

import base64

import boto3
from botocore.credentials import Credentials

ec2 = boto3.client('ec2')

CREDENTIALS = boto3.DEFAULT_SESSION.get_credentials()  # type: Credentials

ZONE_ID = 'eu-central-1b'
VOLUME_ID = 'vol-05bf2a4905dfcba08'
VOLUME_NAME = 'new-mc'
EIP_ID = 'eipalloc-cf4f45e1'
SECURITY_GROUP_ID = 'sg-5a5fdc31'
PRE_BOOT_AMI = 'ami-c7e0c82c'

KEY_NAME = 'Alen new'

INSTANCE_TYPE = 'c4.xlarge'
INSTANCE_BID = 0.10

USER_DATA = f'''#!/usr/bin/env bash

cd /root

mkdir -p .aws
echo '[default]' > .aws/credentials
echo 'aws_access_key_id = {CREDENTIALS.access_key}' >> .aws/credentials
echo 'aws_secret_access_key = {CREDENTIALS.secret_key}' >> .aws/credentials

export TERM="linux"

apt-get update 
apt-get install -y wget python3 python3-requests python3-boto3

wget https://raw.githubusercontent.com/buhanec/ec2-spotter/master/bootstrap.py

chmod +x bootstrap.py

./bootstrap.py {VOLUME_NAME} {EIP_ID} > /root/log.txt
'''

ec2.request_spot_instances(LaunchSpecification={
                             'ImageId': PRE_BOOT_AMI,
                             'InstanceType': INSTANCE_TYPE,
                             'KeyName': KEY_NAME,
                             'EbsOptimized': True,
                             'Placement': {'AvailabilityZone': ZONE_ID},
                             'BlockDeviceMappings': [{
                               'DeviceName' : '/dev/sda1',
                               'Ebs': {
                                 'VolumeSize': 8,
                                 'DeleteOnTermination': True,
                                 'VolumeType' : 'standard'
                               }
                             }],
                             'SecurityGroupIds': [SECURITY_GROUP_ID],
                             'UserData': base64.b64encode(USER_DATA.encode()).decode()
                           },
                           SpotPrice=INSTANCE_BID,
                           Type='persistent',
                           InstanceInterruptionBehavior='terminate')
