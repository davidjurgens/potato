"""
Config module.
"""

import yaml
import os

config = {}


def init_config(args):
    global config

    project_dir = os.getcwd() #get the current working dir as the default project_dir
    config_file = None
    # if the .yaml config file is given, directly use it
    if args.config_file[-5:] == '.yaml':
        if os.path.exists(args.config_file):
            print("INFO: when you run the server directly from a .yaml file, please make sure your config file is put in the annotation project folder")
            config_file = args.config_file
            split_path = os.path.abspath(config_file).split("/")
            if split_path[-2] == "configs":
                project_dir = "/".join(split_path[:-2])
            else:
                project_dir = "/".join(split_path[:-1])
            print("project folder set as %s"%project_dir)
        else:
            print("%s not found, please make sure the .yaml config file is setup correctly" % args.config_file)
            quit()
    # if the user gives a directory, check if config.yaml or configs/config.yaml exists
    elif os.path.isdir(args.config_file):
        project_dir = args.config_file if os.path.isabs(args.config_file) else os.path.join(project_dir, args.config_file)
        config_folder = os.path.join(args.config_file, 'configs')
        if not os.path.isdir(config_folder):
            print(".yaml file must be put in the configs/ folder under the main project directory when you try to start the project with the project directory, otherwise please directly give the path of the .yaml file")
            quit()

        #get all the config files
        yamlfiles = [it for it in os.listdir(config_folder) if it[-5:] == '.yaml']

        # if no yaml files found, quit the program
        if len(yamlfiles) == 0:
            print("configuration file not found under %s, please make sure .yaml file exists in the given directory, or please directly give the path of the .yaml file" % config_folder)
            quit()
        # if only one yaml file found, directly use it
        elif len(yamlfiles) == 1:
            config_file = os.path.join(config_folder, yamlfiles[0])

        # if multiple yaml files found, ask the user to choose which one to use
        else:
            while True:
                print("multiple config files found, please select the one you want to use (number 0-%d)"%len(yamlfiles))
                for i,it in enumerate(yamlfiles):
                    print("[%d] %s"%(i, it))
                input_id = input("number: ")
                try:
                    config_file = os.path.join(config_folder, yamlfiles[int(input_id)])
                    break
                except Exception:
                    print("wrong input, please reselect")

    if not config_file:
        print("configuration file not found under %s, please make sure .yaml file exists in the given directory, or please directly give the path of the .yaml file" % config_folder)
        quit()

    print("starting server from %s" % config_file)
    with open(config_file, "r") as file_p:
        config.update(yaml.safe_load(file_p))

    config.update(
        {
            "verbose": args.verbose,
            "very_verbose": args.very_verbose,
            "__debug__": args.debug,
            "__config_file__": args.config_file,
        }
    )

    # update the current working dir for the server
    os.chdir(project_dir)
    print("the current working directory is: %s"%project_dir)