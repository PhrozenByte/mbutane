from setuptools import setup
import mbutane

with open("README.md") as f:
    readme = f.read()

with open("LICENSE") as f:
    license = f.read()

setup(
    name="mbutane",
    version=mbutane.__version__,
    description="mbutane is a wrapper for Butane that merges multiple human-readable " +
        "Butane Configs and translates them into machine-readable Ignition Configs.",
    long_description=readme,
    author="Daniel Rudolf",
    author_email="mbutane@daniel-rudolf.de",
    url="https://github.com/PhrozenByte/mbutane",
    license=license,
    py_modules=[ "mbutane" ],
    scripts=[ "mbutane" ]
)
