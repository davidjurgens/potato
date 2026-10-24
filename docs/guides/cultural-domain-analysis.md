# Cultural Domain Analysis

Cultural domain analysis studies how the members of a group think about a
set of things: kinds of fruit, illnesses, kin terms. Weller & Romney (1988),
*Systematic Data Collection*, describe the methods Potato supports:

| Method | Potato scheme | What it gives |
|---|---|---|
| Free listing | [`free_list`](../annotation-types/survey/free_list.md) | which items belong to the domain, and how salient each is |
| Triads | [`triad_test`](../annotation-types/survey/triad_test.md) | item-by-item similarity |
| Pile sorts | [`card_sort`](../annotation-types/structured/card_sort.md) | item-by-item similarity, and agreement between informants |
| Questionnaires | `radio`, `select`, `likert` | the input to a cultural consensus analysis |

The `cultural_domain` export turns the answers into the tables and matrices
used in these analyses.

## A study

`examples/advanced/cultural-domain/` runs the three steps in one study:

1. a prestudy page with a free list ("List all the kinds of fruit you can
   think of"),
2. two items, nine fruits and seven vegetables, each with a triad test and an
   open pile sort over the item's list,
3. a poststudy page of eight true/false statements for a consensus analysis.

```bash
python potato/flask_server.py start examples/advanced/cultural-domain/config.yaml -p 8000
```

In a real study the free lists usually come first and the items for the
triads and pile sorts are chosen from them afterwards, which means two
deployments. The example puts all three in one so it can be tried end to end.

## Exporting

```bash
python -m potato.export --config examples/advanced/cultural-domain/config.yaml \
    --format cultural_domain --output out/cultural-domain \
    --option consensus_schemes=cc_tomato,cc_lemon_sweet,cc_banana_tree,cc_grape_raisin,cc_apple_float,cc_lime_green,cc_mango_stone,cc_pear_ripen \
    --option synonyms=data/synonyms.csv
```

| Option | Default | Description |
|---|---|---|
| `normalize` | each scheme's `normalize` | `true`, `false`, or `lowercase`, `trim` (comma-separated). Applied to free-list items before counting |
| `synonyms` | none | A CSV of `variant,canonical` rows (a header row is optional), applied after normalizing. A relative path is looked up from the working directory, then from the project directory |
| `consensus_schemes` | none | Comma-separated scheme names for the consensus analysis |
| `consensus_choices` | the number of labels | The number of options L for questions whose scheme has fewer labels than that |
| `consensus_min_answers` | `2` | Informants with fewer answers are left out of the consensus analysis |

Every file has `schema` and `instance_id` columns (`instance_id` is empty
for a phase page), or a file name ending in `<scheme>` or
`<scheme>_<item>`, so several domains can be exported together.

## Free lists: salience

`freelist_items.csv` has one row per listed item: user, the normalized item,
what was typed, its rank in the list, the list length and the time it was
added. `salience.csv` has one row per item and domain, most salient first:

| Column | Meaning |
|---|---|
| `n_lists` | N, the number of non-empty lists |
| `frequency` | F, the number of lists that mention the item |
| `pct_informants` | 100 × F / N |
| `mean_rank` | the item's average position in the lists that mention it |
| `smith_s` | Smith's S |
| `sutrop_csi` | Sutrop's (2001) cognitive salience index |

For item j, where list i has length L_i and mentions j at rank r_ij
(counting from 1):

    S_j   = (1/N) × Σ_i (L_i − r_ij + 1) / L_i     (sum over lists that mention j)
    CSI_j = F_j / (N × mean rank of j)

An item listed first in a list contributes 1 to the sum, the last item
contributes 1/L_i, and a list that does not mention j contributes 0. S
ranges from 0 to 1.

Before counting, each item is normalized (if asked) and mapped through the
synonym table. An item that then appears twice in one list counts once, at
its first rank, and the list length is the number of distinct items. Blank
items are dropped.

Frequency, percentage, mean rank and Smith's S are the free-list statistics
reported by Borgatti's ANTHROPAC; Sutrop's index is added beside them.

## Pile sorts: co-occurrence

From each `card_sort` answer the export builds an item-by-item matrix with a
1 where two items share a pile. An item can sit in more than one pile when
the scheme has `allow_multiple: true`; two items then count as together if
they share any pile.

- `pilesort_cooccurrence_<scheme>_<item>.csv`: the aggregate proportion
  matrix, the share of informants who put each pair in one pile, out of the
  informants who sorted both items. When everyone sorts every item, the
  denominator is the number of informants.
- `pilesort_informants_<scheme>_<item>.csv`: informant by informant, the
  proportion of item pairs the two informants treated alike (both together,
  or both apart). This is a similarity between informants for checking
  agreement or for a consensus-style analysis of the sorts.
- `pilesort_pairs.csv`: the per-informant matrices in long form (user, item
  pair, same pile 0 or 1), for analysis elsewhere.

The `card_sort` interface is unchanged; the export only reads its answers.
Items left in the "unsorted" area are treated as not sorted by that
informant.

## Triads: similarity

In a triad (a, b, c) where c was chosen as most different, the pair (a, b)
is judged similar. `triads_similarity_<scheme>[_<item>].csv` gives, for each
pair, the number of times it was judged similar divided by the number of
times it was shown together, over all informants. Pairs that were never
shown together are blank. The diagonal is 1. `triads_answers.csv` lists every
answered triad with the positions it was shown in.

With a Steiner design every pair appears in exactly one triad per informant,
so a pair's similarity is the proportion of informants who left it together.

## Cultural consensus

The consensus model (Romney, Weller & Batchelder 1986) asks whether a group
of informants shares one body of knowledge, how much of it each informant
has (their competence), and what the culturally correct answers are. The
input is an informant-by-question table of categorical answers. Name the
schemes in `consensus_schemes`:

- a `radio`, `select` or `likert` scheme on items gives one question per
  item, named `<scheme>:<item id>`;
- the same on a phase page gives one question, named after the scheme.

True/false and multiple-choice questions both work; a scheme's L is the
number of its labels (for a `likert` without labels, its `size`).
`multiselect` schemes are refused with a warning, since an informant can give
several answers to one question.

The analysis, implemented from the papers:

1. **Agreement.** For informants i and j, M_ij is the proportion of the
   questions both answered on which they gave the same answer. It is
   corrected for guessing among L options: M*_ij = (L × M_ij − 1) / (L − 1).
   When the shared questions have different L, the chance rate 1/L is
   averaged over them, which gives the same formula when L is constant.
2. **Competence.** The model says M*_ij = D_i × D_j for i ≠ j, so the
   competences D are the loadings on the first factor of M*. The diagonal of
   M* is unknown. It is estimated by iterated principal axis factoring: start
   from each row's largest off-diagonal value, take the first eigenvector,
   put the squared loadings on the diagonal, and repeat until the diagonal
   stops changing. A loading above 1 is capped at 1 and reported.
3. **One culture?** The eigenvalues of the final matrix are reported. A
   first-to-second eigenvalue ratio above 3 is the usual rule of thumb for
   treating the answers as coming from one shared culture. It is a rule of
   thumb, not a test, and a negative competence is a reason to look at that
   informant whatever the ratio.
4. **Answer key.** Following Batchelder & Romney (1988), with a uniform prior
   over the L options, the posterior probability that option l is the
   culturally correct answer to a question is proportional to the product,
   over the informants who answered l, of ((L − 1) × D_i + 1) / (1 − D_i).
   Competences are clipped to the range 0 to 0.999 here, so an informant with
   a negative competence adds nothing to the weight of the answer they gave.

Files:

- `consensus_informants.csv`: user, competence, number of answers, and
  `negative` = 1 for a competence below 0 (agreeing with the others less
  than chance).
- `consensus_answers.csv`: per question, the estimated answer and its
  posterior probability, the majority answer, and whether the two agree.
- `consensus_summary.json`: number of informants and questions, the
  eigenvalues and their first-to-second ratio, mean competence, the
  informants with negative competence, iteration count and any warnings.

At least three informants are needed. With few questions the competence
estimates are noisy; the model is meant for questionnaires of tens of
questions.

## Troubleshooting

- **No free-list rows.** The export reads `free_list` schemes from
  `annotation_schemes` and from the phase question files. A free list in a
  phase file the export cannot find (check `task_dir`) is skipped.
- **Plural and singular counted separately.** Add rows to the synonyms file,
  for example `apples,apple`.
- **"consensus scheme ... is a multiselect".** Use one `radio` per
  statement.
- **"Nothing to export".** The export found no free-list, triad or pile-sort
  answers and wrote no files, so it fails. `radio`, `select` and `likert`
  answers are used only when `consensus_schemes` names their schemes; in a
  project with no `free_list`, `triad_test` or `card_sort` scheme, pass
  `--option consensus_schemes=...`.
- **Answers on phase pages are missing from auto-export.** Set
  `export_include_phase_data: true`. Without it, auto-export and the CSV and
  TSV exports leave out phase-page answers; `python -m potato.export
  --format cultural_domain` reads them either way.
- **A Heywood case warning.** One informant's competence reached 1. This
  happens with few informants or few questions; add data, or read that
  informant's competence as "at the top of the range" rather than exactly 1.

## References

- Weller, S. C., & Romney, A. K. (1988). *Systematic Data Collection*.
- Romney, A. K., Weller, S. C., & Batchelder, W. H. (1986).
- Batchelder, W. H., & Romney, A. K. (1988).
- Sutrop, U. (2001).

## Related

- [Free lists](../annotation-types/survey/free_list.md)
- [Triad tests](../annotation-types/survey/triad_test.md)
- [Card sorting](../annotation-types/structured/card_sort.md)
- [Export formats](../data-export/export_formats.md)
