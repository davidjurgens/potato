from setuptools import setup, find_packages

setup(
    name='potato-annotation',
    version='1.2.0.21',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'potato = potato.cli:potato',
        ],
    },
    author="Jiaxin Pei",
    author_email="pedropei@umich.edu",
    description="Potato text annotation tool",
    include_package_data=True
)
