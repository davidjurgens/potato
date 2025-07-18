"""
Active Learning Module

This module provides active learning capabilities for the annotation platform.
It implements machine learning algorithms to intelligently select which instances
should be annotated next, based on model confidence and disagreement scores.

The active learning system:
1. Trains classifiers on existing annotations
2. Predicts confidence scores for unlabeled instances
3. Reorders instances to prioritize those with low confidence
4. Maintains a balance between active learning and random sampling

This helps reduce the total number of annotations needed while maintaining
high-quality results by focusing on the most informative instances.
"""

def actively_learn():
    """
    Main active learning function that reorders instances based on model predictions.

    This function implements the core active learning algorithm:
    1. Collects all current annotations from users
    2. Resolves multiple annotations per instance using a specified strategy
    3. Trains classifiers for each annotation scheme
    4. Predicts confidence scores for unlabeled instances
    5. Reorders instances to prioritize low-confidence predictions
    6. Updates user assignment queues while preserving existing annotations

    Side Effects:
        - Trains machine learning models on current annotations
        - Reorders instance assignments for all users
        - Updates active learning state tracking
        - Logs training progress and statistics

    The function maintains a balance between active learning selection and
    random sampling to ensure diversity in the training data.
    """
    global user_to_annotation_state
    global instance_id_to_data

    # Check if active learning is configured
    if "active_learning_config" not in config:
        logger.warning(
            "the server is trying to do active learning " + "but this hasn't been configured"
        )
        return

    al_config = config["active_learning_config"]

    # Skip if the user doesn't want us to do active learning
    if "enable_active_learning" in al_config and not al_config["enable_active_learning"]:
        return

    # Validate required configuration parameters
    if "classifier_name" not in al_config:
        raise Exception('active learning enabled but no classifier is set with "classifier_name"')

    if "vectorizer_name" not in al_config:
        raise Exception('active learning enabled but no vectorizer is set with "vectorizer_name"')

    if "resolution_strategy" not in al_config:
        raise Exception("active learning enabled but resolution_strategy is not set")

    # This specifies which schema we need to use in active learning (separate
    # classifiers for each). If the user doesn't specify these, we use all of
    # them.
    schema_used = []
    if "active_learning_schema" in al_config:
        schema_used = al_config["active_learning_schema"]

    # Get configuration parameters for classifiers and vectorizers
    cls_kwargs = al_config.get("classifier_kwargs", {})
    cls_kwargs = al_config.get("classifier_kwargs", {})
    vectorizer_kwargs = al_config.get("vectorizer_kwargs", {})
    strategy = al_config["resolution_strategy"]

    # Collect all the current labels from all users
    # This creates a mapping from instance ID to list of annotations
    instance_to_labels = defaultdict(list)
    for uas in user_to_annotation_state.values():
        for iid, annotation in uas.instance_id_to_labeling.items():
            instance_to_labels[iid].append(annotation)

    # Resolve all the multiple-annotations to a single one using the provided
    # strategy to get training data
    # This handles cases where multiple users have annotated the same instance
    instance_to_label = {}
    schema_seen = set()
    for iid, annotations in instance_to_labels.items():
        resolved = resolve(annotations, strategy)

        # Prune to just the schema we care about for active learning
        if len(schema_used) > 0:
            resolved = {k: resolved[k] for k in schema_used}

        for s in resolved:
            schema_seen.add(s)
        instance_to_label[iid] = resolved

    # Construct a dataframe for easy processing
    texts = []
    # We'll train one classifier for each scheme
    scheme_to_labels = defaultdict(list)
    text_key = config["item_properties"]["text_key"]
    for iid, schema_to_label in instance_to_label.items():
        # get the text content for this instance
        text = instance_id_to_data[iid][text_key]
        texts.append(text)
        for s in schema_seen:
            # In some cases where the user has not selected anything but somehow
            # this is considered annotated, we include some dummy label
            label = schema_to_label.get(s, "DUMMY:NONE")

            # HACK: this needs to get fixed for multilabel data and possibly
            # number data
            label = list(label.keys())[0]
            scheme_to_labels[s].append(label)

    scheme_to_classifier = {}

    # Train a classifier for each annotation scheme
    for scheme, labels in scheme_to_labels.items():

        # Sanity check we have more than 1 label
        # Active learning requires at least 2 different labels to work
        label_counts = Counter(labels)
        if len(label_counts) < 2:
            logger.warning(
                (
                    "In the current data, data labeled with %s has only a"
                    + "single unique label, which is insufficient for "
                    + "active learning; skipping..."
                )
                % scheme
            )
            continue

        # Instantiate the classifier and the tokenizer
        cls = get_class(al_config["classifier_name"])(**cls_kwargs)
        vectorizer = get_class(al_config["vectorizer_name"])(**vectorizer_kwargs)

        # Train the classifier using a pipeline
        clf = Pipeline([("vectorizer", vectorizer), ("classifier", cls)])
        logger.info("training classifier for %s..." % scheme)
        clf.fit(texts, labels)
        logger.info("done training classifier for %s" % scheme)
        scheme_to_classifier[scheme] = clf

    # Get the remaining unlabeled instances and start predicting
    unlabeled_ids = [iid for iid in instance_id_to_data if iid not in instance_to_label]
    random.shuffle(unlabeled_ids)

    # Calculate the percentage of instances to keep random
    # This ensures we don't bias too heavily toward active learning
    perc_random = al_config["random_sample_percent"] / 100

    # Split to keep some of the data random
    # This maintains diversity in the training data
    random_ids = unlabeled_ids[int(len(unlabeled_ids) * perc_random) :]
    unlabeled_ids = unlabeled_ids[: int(len(unlabeled_ids) * perc_random)]
    remaining_ids = []

    # Cap how much inference we need to do (important for big datasets)
    # This prevents the system from becoming too slow with large datasets
    if "max_inferred_predictions" in al_config:
        max_insts = al_config["max_inferred_predictions"]
        remaining_ids = unlabeled_ids[max_insts:]
        unlabeled_ids = unlabeled_ids[:max_insts]

    # For each scheme, use its classifier to label the data
    # This generates confidence scores for each unlabeled instance
    scheme_to_predictions = {}
    unlabeled_texts = [instance_id_to_data[iid][text_key] for iid in unlabeled_ids]
    for scheme, clf in scheme_to_classifier.items():
        logger.info("Inferring labels for %s" % scheme)
        preds = clf.predict_proba(unlabeled_texts)
        scheme_to_predictions[scheme] = preds

    # Figure out which of the instances to prioritize, keeping the specified
    # ratio of random-vs-AL-selected instances.
    # We select instances with the lowest confidence scores (highest uncertainty)
    ids_and_confidence = []
    logger.info("Scoring items by model confidence")
    for i, iid in enumerate(tqdm(unlabeled_ids)):
        most_confident_pred = 0
        mp_scheme = None
        for scheme, all_preds in scheme_to_predictions.items():

            preds = all_preds[i, :]
            mp = max(preds)
            if mp > most_confident_pred:
                most_confident_pred = mp
                mp_scheme = scheme
        ids_and_confidence.append((iid, most_confident_pred, mp_scheme))

    # Sort by confidence (lowest first for active learning)
    # This prioritizes instances where the model is least confident
    ids_and_confidence = sorted(ids_and_confidence, key=lambda x: x[1])

    # Re-order all of the unlabeled instances
    # Interleave active learning selections with random selections
    new_id_order = []
    id_to_selection_type = {}
    for (al, rand_id) in zip_longest(ids_and_confidence, random_ids, fillvalue=None):
        if al:
            new_id_order.append(al[0])
            id_to_selection_type[al[0]] = "%s Classifier" % al[2]
        if rand_id:
            new_id_order.append(rand_id)
            id_to_selection_type[rand_id] = "Random"

    # These are the IDs that weren't in the random sample or that we didn't
    # reorder with active learning
    new_id_order.extend(remaining_ids)

    # Update each user's ordering, preserving the order for any item that has
    # any annotation so that it stays in the front of the users' queues even if
    # they haven't gotten to it yet (but others have)
    # This ensures that partially annotated instances remain accessible
    already_annotated = list(instance_to_labels.keys())
    for annotation_state in user_to_annotation_state.values():
        annotation_state.reorder_remaining_instances(new_id_order, already_annotated)

    logger.info("Finished reordering instances")