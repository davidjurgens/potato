# Automatic task assignment

Potato can automatically assign instances to annotators based on figurations.

- `on`: whether do automatic task assignment for annotators, default False. If False, all the instances in your input data will 
be displayed to each participant. 
- `sampling_strategy`: how you want to assign the instances to each participant. If `random`, the instances will be randomly assigned.
If set as `ordered`, the instances will be assigned following the order of your input data.
- `labels_per_instance`: how many labels do you need for each instance, default 3
- `instance_per_annotator`: how many instances do you want each participant to annotate, default 5
- `test_question_per_annotator`: how many test instances do you want each annotator to see, default 0

``` YAML
"automatic_assignment": {
"on": True, #whether do automatic task assignment for annotators, default False.
"output_filename": 'task_assignment.json', #no need to change
"sampling_strategy": 'random', #currently we support random assignment or ordered assignment. Use 'random' for random assignment and 'ordered' for ordered assignment
"labels_per_instance": 3,  #the number of labels for each instance
"instance_per_annotator": 5, #the total amount of instances to be assigned to each annotator
"test_question_per_annotator": 0, # the number of attention test question to be inserted into the annotation queue. you must set up the test question in surveyflow to use this function
},
```
