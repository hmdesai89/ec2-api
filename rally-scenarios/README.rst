The concept of benchmark scenarios is a central one in Rally. Benchmark scenarios are what Rally actually uses to test the performance of an OpenStack deployment. They also play the role of main building blocks in benchmark tasks configuration files. Each benchmark scenario performs a small set of atomic operations, thus testing some simple use case

Scenerio in this file is currently work in progress and will be under constant change

Usage:

Install rally2.0 or more via:

sudo apt-get install rally

EC2-api also needs botocore client;

sudo apt-get install botocore

---
Once rally and botocore are installed, we need to create a rally deployment.
For that rally.json file will be used which have username, aws and secret.

if you are using https please give certificate file path


rally deployment create --filename=<rally.json> --name=<Name for deployment>

Give the path of plugin folder in env variable RALLY_PLUGIN_PATHS

Once deployment is successful you can run different scnerios by calling them in .yaml file

rally task start <yamlfile_path>


