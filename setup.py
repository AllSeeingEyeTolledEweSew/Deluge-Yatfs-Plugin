from setuptools import setup, find_packages

setup(
    name="YatfsRpc",
    version="1.0.1",
    description="RPC helper plugin for YATFS.",
    author="AllSeeingEyeTolledEweSew",
    author_email="allseeingeyetolledewesew@protonmail.com",
    url="https://github.com/AllSeeingEyeTolledEweSew/Deluge-Yatfs-Plugin",
    license="Unlicense",
    packages=find_packages(),
    entry_points={
        "deluge.plugin.core": [
            "yatfs = yatfs_plugin:CorePlugin",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Environment :: Plugins",
        "License :: Public Domain",
        "Programming Language :: Python",
        "Topic :: Communications :: File Sharing",
        "Topic :: System :: Networking",
        "Operating System :: OS Independent",
    ],
)
