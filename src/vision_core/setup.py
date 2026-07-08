import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'vision_core'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='taegeon',
    maintainer_email='danielkim3276@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'joint_commander = vision_core.joint_commander:main',
            'pick_place_demo = vision_core.pick_place_demo:main',
            'pose_command_adapter = vision_core.pose_command_adapter:main',
            'robot_move = vision_core.robot_move:main',
        ],
    },
)
