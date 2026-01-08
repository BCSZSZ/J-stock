from setuptools import setup, find_packages

setup(
    name='j-stock-analyzer',
    version='0.1.0',
    author='Your Name',
    author_email='your_email@example.com',
    description='A Japanese Stock Technical Analysis System',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/yourusername/j-stock-analyzer',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
        'jquants-api-client',
        'pandas',
        'pandas_ta',
        'fastparquet',
        'pyarrow',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)