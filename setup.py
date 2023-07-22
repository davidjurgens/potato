from setuptools import setup, find_packages
with open("README.md", "r") as fh:
    long_description = fh.read()
setup(
    name='potato-annotation',
    version='1.2.0.32',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'potato = potato.cli:potato',
        ],
    },
    url="https://github.com/davidjurgens/potato",
    author="Jiaxin Pei",
    author_email="pedropei@umich.edu",
    description="Potato text annotation tool",
    include_package_data=True,
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=[
        'beautifulsoup4>=4.10.0',
        'click>=8.0.3',
        'Flask>=2.0.2',
        'itsdangerous>=2.0.1',
        'Jinja2>=3.0.3',
        'joblib>=1.2.0',
        'simpledorff>=0.0.2',
        'MarkupSafe>=2.0.1',
        'numpy>=1.21.0',
        'pandas>=1.3.5',
        'python-dateutil>=2.8.2',
        'pytz>=2021.3',
        'PyYAML>=6.0',
        'requests>=2.29.0',
        'scikit-learn>=1.0.2',
        'scipy>=1.7.3',
        'six>=1.16.0',
        'soupsieve>=2.3.1',
        'threadpoolctl>=3.0.0',
        'tqdm>=4.62.3',
        'ujson>=5.4.0',
        'Werkzeug>=2.0.2'
    ]
)
