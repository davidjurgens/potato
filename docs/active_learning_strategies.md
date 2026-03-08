# Active Learning Query Strategies

This document provides a comprehensive reference for all query strategies available in Potato's active learning system.

## Overview

Query strategies determine **which instances are presented to annotators next**. By selecting the most informative instances for labeling, active learning reduces the total annotation effort needed to train a good classifier.

Potato supports five query strategies, configurable via the `query_strategy` field in `active_learning`:

```yaml
active_learning:
  enabled: true
  query_strategy: "hybrid"  # uncertainty | diversity | badge | bald | hybrid
```

## Strategy Comparison

| Strategy | Description | Best For | Computational Cost |
|----------|-------------|----------|-------------------|
| `uncertainty` | Lowest classifier confidence | General use, small label sets | Low |
| `diversity` | Maximum feature-space coverage | Imbalanced data, early rounds | Medium |
| `badge` | Uncertainty-weighted diversity (k-means++) | Balanced exploration/exploitation | Medium |
| `bald` | Ensemble disagreement (mutual information) | High-stakes tasks, calibration-sensitive | High (N classifiers) |
| `hybrid` | Weighted combination of strategies | Customizable workflows | Depends on components |

## Detailed Strategy Descriptions

### Uncertainty Sampling (default)

Selects instances where the classifier is **least confident** in its prediction.

**Mathematical formulation:**
```
x* = argmax_x (1 - max_y P(y|x))
```

**When to use:**
- Default choice for most annotation tasks
- Works well with any number of labels
- Best when the model already has some training data

**When not to use:**
- Very early in annotation (no trained model yet)
- When you need coverage of the entire data distribution

**Configuration:**
```yaml
active_learning:
  query_strategy: "uncertainty"
```

### Diversity Sampling

Selects instances that are **farthest from already-annotated data** in the feature space, ensuring broad coverage.

**Mathematical formulation:**
```
x* = argmax_x min_{x' in L} cosine_distance(f(x), f(x'))
```
where `L` is the set of already-labeled instances and `f(x)` is the feature representation.

**When to use:**
- Early annotation rounds with few labels
- Imbalanced datasets where minority classes may be missed
- When you want to explore the full data distribution

**When not to use:**
- When you have enough labeled data for uncertainty to work well
- When computational cost is a concern (requires distance calculations)

**Configuration:**
```yaml
active_learning:
  query_strategy: "diversity"
```

### BADGE (Batch Active learning by Diverse Gradient Embeddings)

Combines uncertainty and diversity by weighting feature vectors by their prediction uncertainty, then selecting diverse points from this weighted space using k-means++ initialization.

**How it works:**
1. Get `predict_proba` output per instance
2. Weight each feature vector by `(1 - max_prob)` as an uncertainty proxy
3. Run k-means++ initialization on weighted vectors to select diverse-uncertain instances

This is an approximation of the full BADGE algorithm (Ash et al., 2020), which uses gradient embeddings from neural networks. Our version works with any sklearn classifier.

**When to use:**
- When you want both uncertainty and diversity in a principled way
- Medium-to-large annotation pools
- When pure uncertainty leads to redundant selections

**Configuration:**
```yaml
active_learning:
  query_strategy: "badge"
```

**Reference:** Ash, J.T., Zhang, C., Krishnamurthy, A., Langford, J., & Agarwal, A. (2020). "Deep Batch Active Learning by Diverse, Uncertain Gradient Lower Bounds." *ICLR 2020*.

### BALD (Bayesian Active Learning by Disagreement)

Trains an **ensemble of classifiers** with different random seeds/bootstrap samples and selects instances with highest **mutual information** — where the ensemble disagrees most.

**Mathematical formulation:**
```
x* = argmax_x [H[y|x] - E_theta[H[y|x,theta]]]
```
where `H[y|x]` is the entropy of the averaged predictions and `E_theta[H[y|x,theta]]` is the average of individual model entropies.

**When to use:**
- High-stakes annotation tasks where selection quality matters most
- When you have enough computational budget for N classifiers
- Tasks with subtle class boundaries

**When not to use:**
- Small datasets (not enough data for meaningful bootstrap)
- When speed is critical (trains N classifiers)

**Configuration:**
```yaml
active_learning:
  query_strategy: "bald"
  bald_params:
    n_estimators: 5         # Number of ensemble members
    bootstrap_fraction: 0.8  # Fraction of data per bootstrap sample
```

**Reference:** Houlsby, N., Huszar, F., Ghahramani, Z., & Lengyel, M. (2011). "Bayesian Active Learning for Classification and Preference Learning."

### Hybrid Strategy

A **weighted combination** of uncertainty and diversity scores. Allows fine-tuning the exploration/exploitation trade-off.

**How it works:**
1. Compute normalized scores from each component strategy
2. Combine with configurable weights: `score = w_u * uncertainty + w_d * diversity`

**Configuration:**
```yaml
active_learning:
  query_strategy: "hybrid"
  hybrid_weights:
    uncertainty: 0.7
    diversity: 0.3
```

The weights must sum to 1.0.

## Cold-Start Strategies

Before `min_instances_for_training` annotations exist, no classifier is available. Potato supports two cold-start strategies:

### Random (default)

Instances are presented in their original order (or random order). No reordering is applied.

```yaml
active_learning:
  cold_start_strategy: "random"
```

### LLM-Based Selection

Based on the ActiveLLM approach (Bayer et al., 2024). Uses an LLM to estimate instance informativeness:

1. Sample a batch of candidate instances
2. Query the LLM for confidence on each
3. Select instances with **moderate confidence** (0.4-0.7 range) — these are on the decision boundary
4. Interleave with random samples for diversity

```yaml
active_learning:
  cold_start_strategy: "llm"
  cold_start_batch_size: 20
  llm:
    enabled: true
    endpoint_url: "http://localhost:8080/v1/chat/completions"
    model_name: "your-model"
```

**Requires:** An LLM endpoint configured in `active_learning.llm`.

**Reference:** Bayer, M., Lutz, J., & Reuter, C. (2024). "ActiveLLM: Large Language Model-Based Active Learning for Textual Few-Shot Scenarios." *TACL*.

## Probability Calibration

Raw `predict_proba` outputs from sklearn classifiers are often poorly calibrated. Potato can wrap the classifier with `CalibratedClassifierCV` using isotonic regression:

```yaml
active_learning:
  calibrate_probabilities: true  # default: true
```

This improves the reliability of uncertainty scores, which directly impacts query selection quality. Calibration requires at least 5 training instances and uses 2-3 fold cross-validation.

## Sentence-Transformer Embeddings

For tasks where bag-of-words features are insufficient (short texts, semantic similarity tasks), use sentence-transformer embeddings:

```yaml
active_learning:
  vectorizer_name: "sentence-transformers"
  vectorizer_params:
    model_name: "all-MiniLM-L6-v2"  # 80MB, fast, 384-dim
```

**Installation:** `pip install sentence-transformers`

**Model options:**
- `all-MiniLM-L6-v2` — Fast, good quality (default)
- `all-mpnet-base-v2` — Higher quality, slower
- `paraphrase-multilingual-MiniLM-L12-v2` — Multilingual support

## Advanced: ICL Ensemble

When both a trained classifier and ICL (In-Context Learning) labeler are available, Potato can combine their predictions:

```yaml
active_learning:
  use_icl_ensemble: true
  icl_ensemble_params:
    initial_icl_weight: 0.7   # ICL weight when few annotations exist
    final_icl_weight: 0.2     # ICL weight after transition_instances
    transition_instances: 100  # Annotations at which weights reach final values
```

The weight interpolates linearly: early on, LLM predictions dominate (good with few examples); as more annotations accumulate, the trained classifier takes over.

This approach is inspired by FreeAL (Xiao et al., 2023) and the collaborative frameworks described in the LLM-based AL survey (Xia et al., 2025).

## Advanced: Annotation Routing

Noise-aware routing between LLM auto-labeling and human annotation, based on Yuan et al. (2024):

```yaml
active_learning:
  annotation_routing: true
  routing_thresholds:
    auto_label_min_confidence: 0.9  # Auto-label above this
    show_suggestion_below: 0.5      # Show LLM suggestion below this
  verification_sample_rate: 0.2     # Spot-check rate for auto-labels
```

- **High LLM confidence (>0.9):** Auto-label, flag for periodic verification
- **Medium confidence (0.5-0.9):** Route to human (most informative)
- **Low confidence (<0.5):** Route to human with LLM suggestion shown

## Troubleshooting

**Training not triggering:**
- Check `min_instances_for_training` — you need this many annotated instances
- Check `update_frequency` — training triggers every N new annotations
- Ensure `schema_names` includes your annotation scheme name

**All instances ranked the same:**
- Check for sufficient label diversity (need at least 2 classes)
- Try a different vectorizer (TF-IDF vs sentence-transformers)
- Increase training data

**BADGE/BALD slow:**
- Reduce `bald_params.n_estimators`
- Set `max_instances_to_reorder` to limit the pool size

**Sentence-transformers not found:**
- Install: `pip install sentence-transformers`
- The package is only imported when configured, not at startup

## References

1. Ash, J.T., et al. (2020). "Deep Batch Active Learning by Diverse, Uncertain Gradient Lower Bounds." *ICLR 2020*.
2. Houlsby, N., et al. (2011). "Bayesian Active Learning for Classification and Preference Learning."
3. Bayer, M., et al. (2024). "ActiveLLM: Large Language Model-Based Active Learning for Textual Few-Shot Scenarios." *TACL*.
4. Yuan, B., et al. (2024). "Hide and Seek in Noise Labels: Noise-Robust Collaborative Active Learning with LLMs-Powered Assistance." *ACL 2024*.
5. Mavromatis, C., et al. (2024). "CoverICL: Selective Annotation for In-Context Learning via Active Graph Coverage." *EMNLP 2024*.
6. Xiao, R., et al. (2023). "FreeAL: Towards Human-Free Active Learning in the Era of Large Language Models." *EMNLP 2023*.
7. Tian, K., et al. (2023). "Just Ask for Calibration: Strategies for Eliciting Calibrated Confidence Scores from Language Models." *EMNLP 2023*.
8. Xiong, M., et al. (2024). "Can LLMs Express Their Uncertainty? An Empirical Evaluation of Confidence Elicitation in LLMs." *ICLR 2024*.
9. Xia, Y., et al. (2025). "From Selection to Generation: A Survey of LLM-based Active Learning." *ACL 2025*.
10. Kholodna, N., et al. (2024). "LLMs in the Loop: Leveraging Large Language Model Annotations for Active Learning in Low-Resource Languages." *ECML-PKDD 2024*.

## See Also

- [Active Learning Guide](active_learning_guide.md) — Full admin configuration guide
- [AI Support](ai_support.md) — LLM endpoint configuration
- [ICL Labeling](icl_labeling.md) — In-context learning setup
