# Model Training

Model training fits a model on the study's own annotations, from the admin
Training page at `/admin/training`: a classifier for choice schemes, a span
tagger for span schemes, an object detector or instance segmenter for image
shapes, a segment tagger for audio, or an LLM fine-tuned on free-text answers
or on pairwise preferences. It can also fine-tune Laya or OpenJev, or
calibrate any decision model (Jev, OpenJev, laya-serve, Laya) to the study's
labels. Each
run resolves the annotations to one
label per item, splits the items into train, val and test, fits the model in a
separate process, and records what it trained on and which items it held out.
A run's predictions can then be written back to items as prelabels, which the
[model review](model_review.md) workflow serves least-confident first.

The labeling engine uses the same trainers. [Distillation](../labeling-engine/configuration.md#distill)
fits one on the engine's labels, and a `trained` source loads a fitted model's
directory (`artifact_dir`).

---

## Quick start

```yaml
model_training:
  enabled: true
```

Restart the server, open `/admin/training`, pick a trainer and a scheme, and
click **Train now**. Nothing is shown to annotators until you name schemes
under `writeback.schemas`.

![The Training page after one run of sklearn-text](../img/screenshots/model_training_page.png)

[`examples/ai-assisted/model-training/`](https://github.com/davidjurgens/potato/tree/master/examples/ai-assisted/model-training)
is a complete project: 160 product reviews, a gold file the
[simulator](../tools/simulator.md) can annotate from, and `sklearn-text`,
which needs nothing beyond a plain install. Its config comments give the
commands. With 120 of the reviews labelled, one run there scored 0.84 val
macro-F1 and published 80 prelabels: on the 40 reviews nobody had labelled
and on the held-out val and test reviews, less 4 below `min_confidence`. A
new annotator then sees the model's answer selected:

![A review with the model's answer selected](../img/screenshots/model_training_prelabel.png)

---

## Configuration

All keys sit under `model_training`:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Registers the `/admin/training` routes and the training manager. Without it the routes do not exist. |
| `retain_runs` | `5` | Finished runs kept in the run ledger. Older runs are dropped from it unless their predictions are still stored. The run directories stay on disk. |
| `grace_seconds` | `20` | After a cancel, seconds the run gets to exit before it is killed. |
| `queue_max` | `10` | Runs that may wait behind the one in progress. See [The run queue](#the-run-queue). |
| `split_seed` | `0` | Seeds the split assignment. Keep it fixed: changing it moves held-out items into training. |
| `splits` | `{train: 0.7, val: 0.15, test: 0.15}` | Split fractions, normalized to sum to 1. Use the names `train`, `val` and `test`: predictions are made for `val` and `test` (and for unlabelled items with `writeback.include_unlabeled`). |
| `aggregation` | `consensus` | How several annotators' labels become one. `consensus` is Dawid-Skene when there is more than one annotator (falling back to majority vote if it fails); `majority` is majority vote. |
| `max_wall_seconds` | unset | Time limit for one run. The server stops a run that exceeds it: a local run is checked each time it reports an event, an ssh or agent run every second. |
| `max_ram_mb` | unset | Address-space limit for the training process (`setrlimit`). Where the platform does not support the limit, the run logs a warning and continues. |
| `device` | `auto` | `auto`, `cpu`, `cuda`, `cuda:N` or `mps`. See [Training on this machine](#training-on-this-machine). |
| `num_threads` | unset | Sets `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` for the run, unless they are already set. |
| `auto_retrain` | off | Retrain as annotations arrive. See below. |
| `writeback` | none | Publish predictions as prelabels. See below. |
| `backend` | `local` | Where runs execute unless the Training page or the API names another. See [Where runs execute](#where-runs-execute). |
| `backends` | none | Named ssh, slurm and agent backends. |
| `max_predictions_mb` | `512` | Largest `predictions.jsonl` a remote agent may upload. |
| `trainer_params` | none | Parameter defaults per trainer. See [Parameters](#parameters). |

### `auto_retrain`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Check for a retrain after every annotation save. |
| `trainer` | none | Trainer name. Required. |
| `schemas` | none | Schemes to train. Required. |
| `min_interval_s` | `600` | Seconds since the last run finished before another starts. |
| `update_frequency` | `25` | New annotations since the last automatic run before another starts. |
| `params` | `{}` | Trainer parameters, as in the `params` of an API run. |
| `backend` | `model_training.backend` | Backend for automatic runs. |
| `accept_licence` | `false` | Confirms the licence of a trainer that asks for it (`ultralytics-detect`, `ultralytics-segment`, `layoutlmv3`). Without it, automatic runs of that trainer are skipped and `skip_reason` says why. |

When a check decides not to start a run, the reason ("waiting for 3 more
annotation(s)", "a run is already in progress", "runs are waiting in the
queue") is in the `skip_reason` field of `GET /admin/training/api/status`.
Automatic runs do not join [the queue](#the-run-queue): the next annotation
saved after the queue empties checks again, with more annotations to train on.

### The run queue

One run executes at a time. A run started from the Training page or the API
while another is in progress waits its turn instead of being refused: the
start returns `202` with `queued: true` and its `position`, and the Runs
table lists it as `waiting #N` with a **Cancel run** button. When the run in
progress ends, the oldest waiting run starts.

- A waiting run is a run-ledger record with status `waiting`, so the queue
  survives a restart: the first waiting run starts when the server comes
  back up. A run the previous server was in the middle of is marked as an
  error, `interrupted`, at the same time.
- Its bundle is built when it starts, not when it is queued, so it trains on
  the annotations as they are then.
- A start that would be refused (an unknown scheme, a parameter the trainer
  does not take) is refused at once, not when its turn comes. A run that
  can no longer start when its turn comes, because its scheme or trainer was
  removed from the config, fails with `invalid_when_dequeued`, and the next
  one starts.
- `"queue": false` in the request body refuses with `409` instead of
  queueing, as before. With `queue_max` runs waiting, a new start is refused
  with `429`.
- `GET /admin/training/api/status` lists the waiting runs in `queue`.

The counts are kept in memory. After a restart, a project that has run before
counts new annotations from the restart, and `min_interval_s` runs from the
last run's finish. A project with no run yet trains once it has
`update_frequency` annotations.

`min_interval_s` and `update_frequency` must be numbers of at least 0, and
`enabled` and `accept_licence` must be `true` or `false`. With `enabled: true`,
`validate` and server start also check the trainer, the schemes and the
parameters, as listed under [Checks before a run](#checks-before-a-run).

### `writeback`

| Key | Default | Meaning |
|---|---|---|
| `schemas` | `[]` | Schemes whose predictions are shown to annotators. Empty means none. |
| `min_confidence` | `0.0` | Predictions below this confidence are not published. A prediction with no confidence passes. |
| `field` | `predictions` | Item field the prelabels are written to. |
| `include_unlabeled` | `false` | Also predict on the items nobody has labelled yet, and prelabel them. Without it a run predicts only on its held-out `val` and `test` items. |

### Example

```yaml
model_training:
  enabled: true
  retain_runs: 5
  split_seed: 0
  splits: {train: 0.7, val: 0.15, test: 0.15}
  aggregation: consensus
  max_wall_seconds: 1800
  max_ram_mb: 4096
  num_threads: 4
  auto_retrain:
    enabled: true
    trainer: sklearn-text
    schemas: [sentiment]
    min_interval_s: 600
    update_frequency: 25
    params:
      classifier: sklearn.linear_model.LogisticRegression
      classifier_kwargs: {max_iter: 1000}
  writeback:
    schemas: [sentiment]
    min_confidence: 0.8
    include_unlabeled: true
```

### Checks before a run

`potato validate` reports an error, and the server does not start, for a
config with any of these. Both list every one they find:

- `splits` with a name other than `train`, `val` and `test`, a fraction that
  is not a number of at least 0, fractions that sum to 0, or no `train`;
- a key `writeback` or `auto_retrain` does not have (`accept_license` is
  reported as a misspelling of `accept_licence`), a `writeback.schemas` entry
  that is not a scheme, or a `min_confidence` outside 0 to 1;
- an enabled `pre_annotation` block whose `field` is not `writeback.field`
  (see [Write-back](#write-back));
- with `auto_retrain.enabled`, a trainer or scheme that does not exist, a
  scheme the trainer cannot learn, parameters the trainer does not take or
  of the wrong type, a `backend` not under `backends`, or a trainer that runs
  only locally (`decision-calibrate`) on another backend;
- a parameter under `trainer_params` that its trainer does not take, or of
  the wrong type;
- under `backends`, a missing or unknown `type`, a key that type does not
  have, an ssh backend with no `host`, a `gpus` value other than `auto`,
  `none` or GPU indices, a backend other than this machine named `local`, or
  a `model_training.backend` that is not defined;
- a decision model's `calibration` file that does not exist (see
  [`decision-calibrate`](#decision-calibrate)).

A run started from the page or the API is checked again when it starts; see
[Routes](#routes) for the status codes.

---

## Where runs execute

A run executes on a *backend*. There are four kinds:

| Type | Where the trainer runs | Who starts it |
|---|---|---|
| `local` | This machine, in a subprocess. Always available, and the default. | Potato |
| `ssh` | Another machine Potato can reach over ssh, such as a GPU server. | Potato, over ssh |
| `agent` | A machine Potato cannot reach, such as a workstation behind NAT. | Someone, with `potato training agent` |
| `slurm` | A cluster's compute node, as a batch job. | Potato: ssh to the login node, then `sbatch` |

The Training page has a **Runs on** menu listing them. `model_training.backend`
sets the default, and an API run or `auto_retrain` can name one with
`backend`.

### Training on this machine

`device` picks the accelerator: `auto` takes CUDA, then Apple's Metal
(`mps`), then the CPU, and `cuda:N` names one GPU. On a Mac with Apple
silicon the transformer trainers and the `sentence-transformers` and `clip`
vectorizers run on Metal with no configuration; `torchvision-detect` and
`torchvision-segment` train on the CPU there (see their sections). A device
that was asked for and is not present falls back to the CPU or another
accelerator, with a warning in the run log. The run log names the device:
"Training on ..." for the transformer and detection trainers,
"Embedding on ..." for `sklearn-text`. `model_card.json` records it too. TF-IDF and other
vectorizers that do not use torch ignore `device`.

`potato training check local config.yaml` prints the device a local run
would use.

### A GPU server over ssh

```yaml
model_training:
  enabled: true
  backend: gpu-server          # the default for runs; omit to keep local
  backends:
    gpu-server:
      type: ssh
      host: gpu.example.edu      # any name ssh accepts, including ~/.ssh/config aliases
      python: /opt/conda/bin/python3
      gpus: auto
      min_free_gpu_mb: 4000
```

For each run, Potato:

1. Connects with `ssh` (key-based authentication; `BatchMode` is on, so a
   password prompt fails instead of hanging).
2. Checks the interpreter and reads `nvidia-smi`. With `gpus: auto` it picks
   the GPU with the most free memory and refuses to start when none has
   `min_free_gpu_mb` free. A host with no GPU at all runs on its CPU.
3. Copies Potato's own Python source to `remote_dir/code/<hash>`. The hash
   covers every `.py` file, so the remote host runs the same code as the
   server, whether that is a release or a working copy. A host that already
   has the hash gets no upload.
4. Opens a reverse forward from a unix socket on the remote host back to this
   server, and starts `python -m potato.training.agent` for the run.
5. The agent downloads the run's bundle, runs the same training worker the
   local backend runs, and sends progress, predictions and the result back
   through the socket.
6. When the run succeeds, Potato copies the artifact directory back into the
   run's `artifacts/`, so the model is on the server as it would be after a
   local run. It then deletes the remote job directory and closes the
   connection.

The remote host needs only Python 3.8 or newer and the trainer's packages.
To check a backend before training, click
**Check** on the Training page or run:

```bash
potato training check gpu-server config.yaml
```

It reports the Python version, every GPU with its free memory, the GPU a run
would get, and which training packages the remote interpreter lacks.
`--json` prints the same as JSON.

| Key | Default | Meaning |
|---|---|---|
| `host` | required | The ssh destination. |
| `description` | none | Free text, returned with the backend by `GET /admin/training/api/backends`. |
| `user`, `port`, `identity_file` | ssh's own | Passed to `ssh` as `-l`, `-p` and `-i`. |
| `ssh_options` | `[]` | More `-o` options, as `["Option=value", ...]`. |
| `python` | `python3` | Interpreter on the remote host. |
| `packages` | `[]` | Packages to install for the trainer. Potato makes a virtual environment with `--system-site-packages` under `remote_dir`, so the host's own CUDA build of torch is reused, and installs these into it once. |
| `gpus` | `auto` | `auto`, `none`, or indices such as `"1"` or `"0,1"`. Sets `CUDA_VISIBLE_DEVICES`. |
| `min_free_gpu_mb` | `2000` | With `gpus: auto`, the free memory a GPU needs. |
| `remote_dir` | `~/.cache/potato-training` | Code cache and job directories on the remote host. |
| `num_threads` | unset | Sets `OMP_NUM_THREADS` and its siblings for the run. Some shared servers set `OMP_NUM_THREADS=1` in login shells. |
| `env` | `{}` | More environment variables for the agent. A `PYTHONPATH` here is added after Potato's code. |
| `fetch_artifacts` | `true` | Copy the artifacts back after a successful run. |
| `max_artifact_mb` | `2048` | Files larger than this stay on the remote host, and the run log names them. |
| `keep_remote` | `false` | Keep the remote job directory after the run. |
| `connect_timeout_s` | `15` | ssh connection timeout. |
| `heartbeat_timeout_s` | `120` | A run whose agent sends nothing for this long fails. |
| `queue_timeout_s` | unset | Seconds a run may wait to start before it fails. |

**What the remote host can see.** The forward is a unix socket in the remote
`/tmp`, created with mode `0600`, so only the account Potato logged in as can
connect through it. Requests that arrive through it are loopback requests to
this server, and with `debug: true` Potato grants admin access to loopback
requests, so anyone who can use that account on the remote host has admin
access while a run is in progress. The run's token reaches the agent on stdin
and is never in a command line, because command lines are visible to every
account on a shared server. The token is valid for that run only.

### A SLURM cluster (`type: slurm`)

On a cluster, the machine Potato can reach over ssh is usually a login node
with no GPUs, and the GPUs are on compute nodes that only the scheduler
starts work on. A `slurm` backend connects to the login node the way an `ssh`
backend connects to a GPU server. The agent runs there, and the training
worker goes to a compute node as a batch job:

```yaml
model_training:
  enabled: true
  backends:
    cluster:
      type: slurm
      host: login.cluster.example.edu
      python: /opt/conda/bin/python3        # on the login node, for the agent
      job_python: /opt/conda/bin/python3    # on the compute nodes, for the worker
      remote_dir: /shared/projects/me/potato-training   # storage the compute nodes share
      gres: gpu:1
      time: "04:00:00"
      nice: 0
```

For each run, Potato connects to the login node and copies its code there, as
for `ssh`. The agent then:

1. Downloads the bundle into `remote_dir/jobs/<run>/`.
2. Writes `job.sh` and submits it with `sbatch`. The job runs the worker on
   a compute node. The worker's events go to `events.jsonl`, its errors to
   `stderr.log` and its exit code to `exit_code`, all in the job
   directory. SLURM's own output goes to `slurm.out`.
3. Reads `events.jsonl` as it grows and sends the progress back to this
   server, as an `ssh` backend's agent does. The run log records each change
   in the job's queue state, such as `SLURM job 4242: PENDING (Priority)` or
   `RUNNING on node07`. It runs `squeue` once per `poll_interval_s`.
4. When the job ends, uploads its predictions and reports the result. The
   artifacts come back and the job directory is removed, as for `ssh`.

Cancelling a run sends `scancel --full --signal=TERM`, then `scancel` if the
worker has not stopped after `grace_seconds`. If the ssh session to the login
node drops, the agent cancels its job, so a lost connection does not leave a
GPU allocated.

When the scheduler ends a job (its time limit, a node failure, preemption,
running out of memory, or an `scancel` from outside Potato), the run fails
with that reason, taken from `scontrol show job`. SLURM keeps a finished job
there for a few minutes (`MinJobAge`) even without an accounting database.
A job that finished normally can take a while to show its `exit_code` on the
login node, because NFS caches directory contents: 48 seconds was measured on
one cluster. The agent waits up to `exit_grace_s` for it before it gives up.

Only `sbatch`, `squeue`, `scancel` and, where present, `scontrol` are used,
so a cluster with `srun` disabled and no accounting database (`sacct`) works. GPUs come from `gres`;
the scheduler sets `CUDA_VISIBLE_DEVICES`, and `gpus` is not a setting here.
**Check** on the Training page confirms the login node has the three
commands and that `remote_dir` is not under `/tmp`. It cannot see which
packages the compute nodes have, so a missing package shows up as a failed
run.

Every `ssh` key applies except `gpus` and `packages`. A virtual environment
made on the login node may not run on the compute nodes, so point
`job_python` at an interpreter or environment the compute nodes have.

| Key | Default | Meaning |
|---|---|---|
| `remote_dir` | required | On storage the compute nodes share: the job reads the bundle and writes the model there. `/tmp` is refused. |
| `job_python` | `python` | The worker's interpreter on the compute nodes. |
| `gres` | none | `sbatch --gres`, such as `gpu:1` or `gpu:A6000:1`. With none, the job gets no GPU. |
| `time` | `04:00:00` | `sbatch --time`. The job is killed when it runs out, and the run fails with that reason. Above 6 hours the run log warns. |
| `nice` | `0` | `sbatch --nice`, 0 to 2000. |
| `partition` | the cluster's default | `sbatch --partition`. |
| `cpus_per_task`, `mem` | the cluster's defaults | `sbatch --cpus-per-task` and `--mem`. |
| `sbatch_options` | `[]` | More flags, such as `["--requeue", "--constraint=a100"]`. `--output`, `--chdir`, `--job-name` and `--parsable` are Potato's. |
| `prelude` | `[]` | Shell lines run in the job before the worker, such as `module load cuda/12.4` or `source ~/envs/train/bin/activate`. |
| `poll_interval_s` | `30` | Seconds between `squeue` calls, at least 10. |
| `exit_grace_s` | `180` | After a job leaves the queue, seconds to wait for its `exit_code` to appear on the login node before the run fails. At least 20. |
| `job_name` | `potato-train` | Prefix of the job name; the run id's first 8 characters follow it. |

An agent started by hand can submit to SLURM too, when the login node can
reach this server: `potato training agent --server ... --backend <name>
--workdir <shared dir> --slurm-config slurm.json`. `slurm.json` holds the
settings above as a JSON object.

### A machine Potato cannot reach (`type: agent`)

```yaml
model_training:
  enabled: true
  backends:
    lab-workstation:
      type: agent
      queue_timeout_s: 3600
```

Issue a token on the server, then start the agent on the training machine:

```bash
# On the server
potato training register lab-workstation config.yaml

# On the training machine, which needs Potato and the trainer's packages
export POTATO_TRAINING_TOKEN=<the token>
potato training agent --server https://annotate.example.edu --backend lab-workstation
```

The agent polls the server and runs jobs for its backend until stopped.
`--token-file` reads the token from a file instead of
`POTATO_TRAINING_TOKEN`, `--python` names the interpreter the training worker
runs in (default: the agent's own), `--once` exits after one job,
`--workdir` moves its files (default `~/.cache/potato-training`), and
`--keep` keeps each job's bundle. The agent
needs no inbound port: it opens every connection, and a cancel reaches it in
the response to its next progress report. Registering the name again issues a
new token and invalidates the old one.

A run for an agent backend waits in the `queued` state until an agent asks
for work. With `queue_timeout_s` set, it fails after that many seconds with no
agent. Without it, it waits until cancelled.

Model files from an `agent` backend stay on that machine; only predictions
and the result come back. The run record's `artifact_uri` names where they
are.

An agent backend takes `type`, `description`, `heartbeat_timeout_s` (default
120) and `queue_timeout_s`, with the meanings in the ssh table above, and no
other key.

---

## Trainers

| Trainer | Schemes | Items | Install |
|---|---|---|---|
| `sklearn-text` | `radio`, `select`, `likert`, `multiselect` | text, images | nothing |
| `hf-text-classification` | `radio`, `select`, `likert`, `multiselect`, `soft_label` | text | `potato-annotation[train-text]` |
| `setfit` | `radio`, `select`, `likert`, `multiselect` | text | `potato-annotation[embeddings]` |
| `hf-token-classification` | `span` | text | `potato-annotation[train-text]` |
| `hf-image-classification` | `radio`, `select`, `likert`, `multiselect` | images | `potato-annotation[train-vision]` |
| `llm-sft` | `text` (free-text answers), `trajectory_edit` | text | `potato-annotation[train-llm]` |
| `llm-dpo` | `pairwise` in `binary` mode, `trajectory_edit` | text | `potato-annotation[train-llm]` |
| `prm-reward` | `process_reward` | agent traces | `potato-annotation[train-text]` |
| `reward-model` | `pairwise` (`binary` and `scale`), `ranking`, `bws` | text | `potato-annotation[train-text]` |
| `hf-relation` | `span_link`, `event_annotation`, `coreference` | text | `potato-annotation[train-text]` |
| `hf-conversation-tree` | `tree_annotation` | conversation trees | `potato-annotation[train-text]` |
| `byt5-gloss` | `interlinear_gloss` | text | `potato-annotation[train-text]` |
| `torchvision-detect` | `image_annotation`, `microscopy`, `geo_annotation`, `spectrogram_annotation` | images, slides, OME stacks, rasters, recordings | `potato-annotation[train-vision]` |
| `ultralytics-detect` | `image_annotation`, `microscopy`, `geo_annotation`, `spectrogram_annotation` | images, slides, OME stacks, rasters, recordings | `pip install ultralytics` (AGPL-3.0) |
| `torchvision-segment` | `image_annotation`, `microscopy`, `geo_annotation` (outlines) | images, slides, OME stacks, rasters | `potato-annotation[train-vision]` |
| `ultralytics-segment` | `image_annotation`, `microscopy`, `geo_annotation` (outlines) | images, slides, OME stacks, rasters | `pip install ultralytics` (AGPL-3.0) |
| `cellpose` | `image_annotation`, `microscopy` (outlines) | images, OME stacks | `pip install cellpose` |
| `sam-finetune` | `image_annotation` (outlines) | images | `potato-annotation[train-vision]` |
| `layoutlmv3` | `image_annotation` on pages with a `words` field | page images | `potato-annotation[train-vision]` (weights CC BY-NC-SA 4.0) |
| `vlm-sft` | `text` on image items, `region_caption`, `grounding_eval`, `gui_trajectory` | images, screenshots | `potato-annotation[train-vision]`; a GPU |
| `hf-audio-tagger` | `audio_annotation` | audio | `potato-annotation[train-audio]` |
| `whisper-asr` | `speech_transcript` (corrected turns) | audio | `potato-annotation[train-audio]` |
| `diarization` | `tiered_annotation` (a speaker tier), `audio_annotation` (labels are speakers) | audio | `potato-annotation[train-audio]` |
| `volume-unet` | `volume_annotation` (painted masks) | NIfTI volumes, DICOM series | `potato-annotation[train-vision,volumes]`; a GPU in practice |
| `external-3d` | `spatial_annotation` (cuboids) | point clouds | your own detector (OpenPCDet, MMDetection3D) on the training host |
| `video-track` | `video_annotation` in `tracking` or `combined` mode | video | `potato-annotation[train-vision]` and `opencv-python` |
| `rdkit-property` | `radio`, `select`, `likert`, `slider` about a molecule | a `molecule` display field, or a `chemical_structure` answer | `potato-annotation[chemistry]` |
| `peak-cnn` | `peak_picking` | spectra (JCAMP-DX, mzML, CSV, inline) | `potato-annotation[train-vision]` |
| `signal-cnn` | `interval_label` (epoch or free mode) | signals (EDF, BDF, WFDB, CSV, Parquet, inline) | `potato-annotation[train-vision]`; WFDB and Parquet need `[signals]` |
| `episode-model` | `episode_annotation` (phases, outcome, reward) | robot episodes (LeRobot, HDF5, episode manifests) | `potato-annotation[train-vision]` |
| `decision-calibrate` | `radio`, `select`, `likert`, `slider` | text | nothing; a configured decision model |
| `laya-finetune` | `radio`, `select`, `likert`, `slider` | text | `potato-annotation[decision]` |
| `openjev-finetune` | `radio`, `select`, `likert`, `slider` | text | `pip install wev-ai`; a GPU with about 16 GB free |
| `label-studio-ml` | `radio`, `select`, `multiselect`, `span`, `image_annotation` | text, images | nothing; a running Label Studio ML backend |
| `openai-vlm-boxes` | `image_annotation` | images | nothing; a vision model behind an OpenAI-compatible API |
| `hf-inference` | `radio`, `select`, `multiselect`, `span`, `image_annotation` | text, images | nothing; a Hugging Face Inference Endpoint or serverless model |
| `roboflow` | `image_annotation` | images | nothing; a Roboflow model and API key |
| `cvat-nuclio` | `image_annotation` | images | nothing; a CVAT serverless (Nuclio) function |

`pip install "potato-annotation[train]"` installs what the text, image,
audio and LLM trainers need. Laya (`[decision]`), `wev-ai`, `ultralytics`,
`cellpose`, RDKit (`[chemistry]`) and Opacus (for [`dp`](#differential-privacy-dp))
are separate installs. None of these is part of `potato-annotation[all]`,
because torch is a multi-gigabyte install. A trainer that is not installed is
listed on the Training page as "not installed", with the command that
installs it.

For each scheme, the Training page offers only the trainers that fit it: its
kind, and whether the items are text, images or audio. A trainer the project
cannot run is listed with the reason, such as `decision-calibrate` with "no
decision model is configured". Until you pick a trainer, `sklearn-text` is
selected when it fits. A run started for a scheme that does not exist, or one
the trainer cannot learn, is refused with HTTP 400 before anything is built.
Every trainer except `decision-calibrate` runs on any
[backend](#where-runs-execute).

**One scheme per run.** The page sends one scheme. The API accepts a list,
but every trainer fits only the first scheme named.

### Parameters

A run's parameters come from three places, each overriding the one before:

1. the trainer's defaults (the tables below);
2. `model_training.trainer_params.<trainer>` in the config;
3. the run's own `params`: the **Parameters** field on the Training page, the
   `params` of an API run, or `auto_retrain.params`.

```yaml
model_training:
  enabled: true
  trainer_params:
    hf-text-classification:
      model_name: answerdotai/ModernBERT-base
      epochs: 4
    llm-sft:
      model_name: Qwen/Qwen2.5-1.5B-Instruct
      gradient_checkpointing: true
```

The Parameters field is JSON, filled in from `trainer_params` for the chosen
trainer, and the note under it lists the names the trainer takes. A name the
trainer does not take is refused when the run starts, and at boot when it is
under `trainer_params`, with the list of names it does take. The run page
shows the parameters a run used.

`hf-text-classification`, `hf-token-classification`, `hf-image-classification`
and `hf-audio-tagger` take these. The other trainers list their own parameters
in their sections:

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | per trainer | A Hugging Face model id or a local directory. |
| `epochs` | 5 (token 8, audio 10) | Passes over the training split. |
| `batch_size` | 16 (token and audio 8) | Items per step. |
| `gradient_accumulation` | 1 | Batches per optimizer step: a larger effective batch without the memory. |
| `learning_rate` | text 3e-5, tokens 5e-5, images 5e-5, audio 5e-5 | With `lora`: 2e-4, 3e-4, 5e-4 and 5e-4. |
| `weight_decay` | 0.01 | AdamW weight decay. |
| `warmup_ratio` | 0.1 | Share of steps spent warming the learning rate up, before a linear decay. |
| `patience` | 2 (token and audio 3) | Stop after this many epochs without a better val score; `null` trains every epoch. |
| `precision` | `auto` | `auto` or `bf16` trains in bf16 on a GPU that supports it and in fp32 elsewhere; `fp32` forces full precision. |
| `lora` | off | `true` trains a LoRA adapter (r 16, alpha 32, dropout 0.05) instead of every weight; or an object with `r`, `alpha`, `dropout`, `target_modules` and `quantize` (see [QLoRA](#qlora-4-bit-base-weights)). |
| `min_instances` | 20 (audio 10) | Refuse to fit with fewer items in the train split. |

With a val split, these trainers keep the checkpoint from the epoch that scored
best on val. That makes val a split the trainer has looked at, so the run's
held-out score is taken from test (see [Held-out scores](#held-out-scores)).

### `sklearn-text`

`sklearn-text` needs no optional install for text, because scikit-learn is a
core dependency.

- **Kinds:** `nominal` (`radio`, `select`), `ordinal` (`likert`) and
  `multilabel` (`multiselect`). A multilabel target is trained as one class per
  combination of labels.
- **Modalities:** `text` and `image`.

Parameters, set as described in [Parameters](#parameters):

| Parameter | Default | Meaning |
|---|---|---|
| `classifier` | `sklearn.linear_model.LogisticRegression` | Dotted path to any scikit-learn-API estimator. An `SVC` gets `probability: true` so it can report confidence. |
| `classifier_kwargs` | `{}` | Passed to the estimator's constructor. |
| `vectorizer` | `sklearn.feature_extraction.text.TfidfVectorizer` | A dotted path, `sentence-transformers`, or `clip` (also `image`) for images. On an image corpus the default is `clip`. |
| `vectorizer_kwargs` | `{}` | For a dotted path, passed to the constructor (`ngram_range` may be a list). For `sentence-transformers`, `model_name` (default `all-MiniLM-L6-v2`). For `clip`, `model_name` (default `clip-ViT-B-32`), `cache_dir` and `image_root`. |
| `calibrate` | `true` | Calibrate the confidences, and keep the calibrated model only if it did not cost more than 0.05 training accuracy. Skipped below 50 training items, or when the smallest class has fewer than 2. Platt scaling below 1000 items, isotonic from there. |
| `min_instances` | `10` | Refuse to fit with fewer items in the train split. |

The classifier and vectorizer take dotted paths only. The short names that
[active learning](active_learning_guide.md) accepts (`tfidf`, `logistic`) are
not expanded here: a name that cannot be imported falls back to the default
with a warning in the run's log.

On an [image corpus](#image-items) the default vectorizer is `clip`.

A text vectorizer always reads the item's text (the `text_key` field), never a
media or URL field. The run's `model_card.json` records `input: text` or
`input: media`, and prediction feeds the model the same input it was fitted on.

`sentence-transformers` and `clip` need
`pip install "potato-annotation[embeddings]"` (`clip` also needs `pillow`).
When they are missing, the run fails with the install command.

Accuracy on the training split is recorded as `train_accuracy`. It is never
the run's score.

### `hf-text-classification`

Fine-tunes any model `AutoModelForSequenceClassification` loads. Default model:
`distilbert/distilroberta-base`.

- `multiselect` gets one sigmoid output per label, and a label is predicted
  when its probability reaches `threshold` (default 0.5). The prelabel is the
  list of predicted labels.
- `radio`, `select` and `likert` get a softmax over the labels. A `likert` is
  treated as categories.
- A decoder LLM works too: transformers gives Qwen, Llama, Mistral and others
  a classification head. Use `lora: true` for these.

```json
{"model_name": "Qwen/Qwen2.5-0.5B", "lora": true, "batch_size": 8}
```

It also takes `max_length`, the tokens kept per item (default 256).

#### Learning from disagreement

A bundle normally keeps one label per item, the one the annotators' vote
(or Dawid-Skene) settled on, and drops how they split. With
`soft_targets: true`, an item that two or more annotators labelled trains
toward their split instead: two of three said `positive`, so the target is
0.67 `positive` and 0.33 `negative`, by cross-entropy against that
distribution. For a `multiselect`, each label trains toward the share of
annotators who ticked it. Items with one annotator train on their label as
before.

The model then stays unsure where people disagreed, rather than confident in
whichever label the vote kept. Each prediction carries its `probabilities`,
and the held-out score adds, on the val and test items that have a vote
split:

| Metric | Meaning |
|---|---|
| `soft_jsd` | Jensen-Shannon divergence (bits, 0 to 1) between the model's distribution and the annotators' split |
| `soft_cross_entropy` | Cross-entropy of the annotators' split under the model's distribution |
| `ece` | Expected calibration error of the top label against the voted label, over 10 confidence bins |

A `soft_label` scheme, where each annotator gives a distribution with
sliders, always trains this way. Its target is the annotators' mean
distribution, the prediction is a distribution (`distribution` in the
payload), and the prelabel sets the sliders to it, rounded to whole numbers
that add up to the scheme's `total`. Its headline is
`distribution_agreement`, 1 minus the Jensen-Shannon divergence from the
annotators' distribution.

```json
{"soft_targets": true}
```

#### Choosing what to ask next

[`assignment_strategy: llm_confidence`](../advanced/task_assignment.md)
serves items least-confident first. `acquisition` replaces that ordering with
a score written on each prediction as `acquisition`, highest first:

| `acquisition` | Score |
|---|---|
| `least_confident` (default) | None written; items are ordered by confidence, as before |
| `margin` | 1 minus the gap between the top two probabilities |
| `entropy` | Entropy of the predicted distribution, scaled to 0–1 |
| `bald` | Mutual information between the label and the model's weights, from `mc_samples` (default 10) forward passes with dropout on. It is high for items the model is unsure about for lack of data, and low for items that are ambiguous whatever the data. A model with no dropout cannot give it; the run then logs a warning and scores by entropy. |
| `coreset` | Greedy k-centre over the model's embeddings: each item's distance to the nearest training item or already-chosen item, scaled to 0–1. Spreads the queue across the data, so ten near-copies of one hard item do not take the first ten places. |

Items with an acquisition score are served first, then items that only have
a confidence, then items with a prediction and no confidence, then items with
no prediction. The [`model_review`](model_review.md) strategy still orders
by confidence, because it looks for the model's wrong answers; an acquisition
score ranks the items most worth labelling.

`acquisition` is for single-label schemes (`radio`, `select`, `likert`). `hf-image-classification` takes the same two parameters. The
order reads published prelabels, so as with confidence ordering the scheme
must be in `writeback.schemas`, and `writeback.include_unlabeled: true` is
needed for the unlabelled items to get a prediction and a score at all.

```json
{"acquisition": "bald", "mc_samples": 10}
```

#### Differential privacy (`dp`)

`dp` trains with DP-SGD (Opacus), so the released model reveals little about
any one annotated item. `hf-image-classification` takes it too.

```json
{"dp": {"epsilon": 8, "delta": 1e-5, "max_grad_norm": 1.0}}
```

| Key | Default | Meaning |
|---|---|---|
| `epsilon` | required | The privacy budget for the whole run. Smaller is more private and noisier; 1 to 10 is usual. |
| `delta` | 1 / (10 × train items) | The chance the guarantee does not hold. It must be below 1 / train items. |
| `max_grad_norm` | 1.0 | Each item's gradient is clipped to this norm before noise is added. |

Each step draws its batch by Poisson sampling: every train item is in it
independently, with probability 1 / batches per epoch (about `batch_size` /
train items; the run log gives the exact rate). Each item's
gradient is clipped, and Gaussian noise is added. Opacus sizes the noise so
that the planned `epochs` spend at most `epsilon`. The run reports the epsilon
spent after each epoch (`dp_epsilon`, from the RDP accountant), and the model
card's `dp` entry records the target, the epsilon spent, delta, the noise
multiplier and the clip. Stopping early on `patience` spends less.

The guarantee covers the train split. It does not cover the val split, whose
score picks the epoch kept, or the label list, which is read from the data.
Under DP, mixed precision and gradient accumulation are off, and a quantized
base model (`lora.quantize`) is refused. A text transformer's position and
token-type embedding tables are frozen: their input is one row shared by the
whole batch, which Opacus cannot take per-item gradients through. A layer
Opacus does not support, such as BatchNorm, fails the run at its start with the
layer named. Without Opacus installed (`pip install opacus`), a run with `dp`
is refused before it starts.

### `setfit`

The SetFit method (Tunstall et al., 2022): fine-tune a sentence-transformer on
pairs of labelled items, so items with the same label embed close together,
then fit a logistic regression on the tuned embeddings. It is built for the
first days of a project, from about eight items per label. It runs on
sentence-transformers and scikit-learn and does not need the `setfit` package.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `sentence-transformers/all-MiniLM-L6-v2` | A sentence-transformers model. |
| `num_iterations` | 20 | Pairs drawn per item: this many with the same label and this many with a different one. |
| `max_pairs` | 20000 | Cap on the pairs; 0 for none. |
| `epochs` | 1 | Passes over the pairs. |
| `batch_size` | 16 | Pairs per step. |
| `learning_rate` | 2e-5 | |
| `weight_decay`, `warmup_ratio` | 0.01, 0.1 | As in [Parameters](#parameters). |
| `precision` | `auto` | As in [Parameters](#parameters). |
| `threshold` | 0.5 | `multiselect` only. |
| `min_instances` | 8 | |

For a `multiselect`, a pair's target similarity is the overlap of the two
items' label sets (Jaccard), and there is one logistic head per label.

### `hf-token-classification`

Tags spans for a `span` scheme, such as named entities, error spans or
evidence. Each
annotated span becomes B/I/O tags over the tokens it covers, and predicted
tags are decoded back into character offsets, which is what a span prelabel
needs. Default model: `distilbert/distilroberta-base`. The model needs a fast
tokenizer, because the offsets come from it; a model without one is refused
with that reason.

- Offsets are positions in the item's text field (`text_key`), as Potato's
  span annotations of plain text record them.
- An item longer than `max_length` tokens (default 256) is cut into windows
  that share `stride` tokens (default 64), in training and in prediction, so
  the whole text is tagged.
- B/I/O tags cannot hold two spans over the same characters. Where annotated
  spans overlap, the longest is kept and the run log counts the others.
- Only items with at least one span are trained on. An item annotated with no
  spans looks the same as one nobody annotated, so neither is used as an
  example of text with nothing to tag.

### `hf-image-classification`

Fine-tunes a vision model, any that `AutoModelForImageClassification` loads:
ViT, DeiT, BEiT, ConvNeXt, Swin, DINOv2. Default model:
`google/vit-base-patch16-224-in21k`. It reads images as
[Image items](#image-items) describes: rows whose image it cannot read are
left out and get no prediction. A `multiselect` label is predicted when its
probability reaches `threshold` (default 0.5).

`lora: true` trains a LoRA adapter and the classification head. peft has no
default LoRA targets for most vision models, so every linear layer is adapted,
and the run log says so. `flip` (default `true`) mirrors
training images at random; set it to `false` when a flip changes the label,
as with text in images or left and right.

### Image items

How the image trainers (`sklearn-text` with `clip`, `hf-image-classification`,
`torchvision-*`, `ultralytics-*`) find an item's image, and when a choice
scheme counts as an image corpus.

A `radio`, `select`, `likert` or `multiselect` scheme is an image corpus when
at least 80% of its labelled items carry an image reference ending in `.jpg`,
`.jpeg`, `.png`, `.bmp`, `.webp`, `.tif`, `.tiff` or `.gif`. A remote
`http(s)` image counts only when the item has no other text (its text field
is empty or is the URL itself). On an image corpus the Training page offers
the image trainers, and `sklearn-text` uses CLIP image embeddings unless the
run names a vectorizer:

```bash
pip install "potato-annotation[embeddings]" pillow
```

```yaml
item_properties:
  id_key: id
  text_key: image_url

annotation_schemes:
  - annotation_type: radio
    name: species
    description: Which animal is in the photo?
    labels: [cat, dog, bird]

model_training:
  enabled: true
```

```json
{"id": "img_001", "image_url": "data/images/img_001.jpg"}
```

Where the image reference comes from: the scheme's `source_field` if set,
otherwise the first non-empty item field among `image_url`, `image`,
`image_path`, `file_name`, `audio_url`, `audio`, `audio_path`, `video_url`,
`video`, `video_path`, `url` and `path`.

**Images must be local files, inside the project.** A relative path is resolved against
`task_dir`, or against the task's `media_directory` when it is not found
there (the deep-zoom viewer takes a path inside `media_directory`, such as
`slide_01.svs`). A URL-style path such as `/media/img_001.jpg` (what the
annotation page uses) is resolved against `media_directory`. The file is
linked into the run's bundle. A file outside the task directory and
`media_directory`, by an absolute path, `../` or a symbolic link, is left out
with a warning: the annotation page cannot show it either, and a remote run
would download it. Remote `http(s)` URLs are not downloaded. An image run
leaves out every row whose image is remote or missing, and the run log says
how many; the model gives no prediction for such items. Download remote images
into `media_directory` to train on them.

To train an image corpus on text instead, name a text vectorizer in `params`.

A GUI trace's screenshots (`gui_trajectory`) are read from each step, and an
inline `data:image/...;base64,` screenshot is written into the bundle as a
file. A caption or grounding scheme's image is the `source_field` of the
`image_annotation` scheme it draws on.

### Whole slides and other large images

The detection and segmentation trainers resize each image to a few hundred
pixels, which is no use for a 100,000-pixel pathology slide or a satellite
scene. So when a run's bundle is built for an `image_annotation`,
`microscopy` or `geo_annotation` scheme, a large image is cut into tiles on
the Potato host:

- **Train:** the tiles that contain an annotated object, with each object
  clipped to its tile. Also a sample of empty tiles, so the model sees what
  is not an object.
- **Val, test and unlabeled:** every tile over tissue, or every tile of an
  image that is not a slide, up to `max_predict_tiles` per image.

Each image's split is decided before it is cut, so the tiles of one slide
are never in two splits. After prediction, each tile's shapes are mapped
back onto the whole image. Where tiles overlap, an object both tiles found
is kept once: per label, the most confident copy of two boxes that overlap
at IoU 0.5, or, when one lies mostly inside the other and was cut by its
tile's inner edge, the larger one (the other tile saw only part of it). An
object inside another that was not cut, such as a nucleus inside a cell with
the same label, is a second object and stays, unless it too touches the
inner edge of its tile, when it is taken for a cut copy. Points two tiles
found within 4 full-resolution pixels of each other are one point. Held-out scores are computed on the
whole images, and the prelabels are in the whole image's coordinates, the
ones the deep-zoom viewer stores.

```yaml
model_training:
  enabled: true
  tiling:
    tile_size: 1024
    overlap: 128
    downsample: 2        # train a 40x slide at 20x
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `auto` | `auto` tiles slide formats (`.svs`, `.ndpi`, `.mrxs`, `.scn`, ...) and images whose longer side is at least `auto_min_side`; `true` tiles every image; `false` never tiles. |
| `auto_min_side` | 4096 | |
| `tile_size` | 1024 | Side of a tile, in the pixels the trainer sees. |
| `overlap` | 128 | Pixels neighbouring tiles share, at most half of `tile_size`. Keep it at least as large as the objects: a larger object is found in pieces, one per tile. |
| `downsample` | 1 | Full-resolution pixels per tile pixel. |
| `mpp` | none | Microns per tile pixel. Overrides `downsample` for a slide that records its resolution. |
| `background` | 0.25 | Empty tiles sampled per tile with an object. |
| `max_predict_tiles` | 2000 | The tiles with the most tissue are kept when an image has more. |
| `min_visible` | 0.4 | Share of an object that must be inside a tile for it to train there. A piece covering a quarter of the tile trains whatever its share. |
| `tissue_threshold` | 0.05 | Share of a slide tile that must be tissue to predict on it. |

Slides are read with openslide (`pip install "potato-annotation[wsi]"`) and
other images with Pillow, on the machine that builds the bundle. Tiles are
written into the bundle as JPEG (slides) or PNG, and the link to the whole
image is removed, so a remote backend downloads the tiles, not the slide.

Tissue is the part of a slide's thumbnail darker than Otsu's threshold on
its brightness. A slide with no bare glass is split in two by that
threshold, and its paler half is skipped; set `tissue_threshold: 0` for
such slides.

The empty training tiles assume that every object on an annotated image was
drawn. For slides annotated in part, set `background: 0`, or the model is
taught that the objects nobody drew are background.

### Microscopy and maps

A `microscopy` scheme's ROIs train the detection and segmentation trainers
and `cellpose`. Each z-slice and time point with ROIs on it is rendered with
the scheme's default channels and contrast, by the same compositor the
viewer uses, and becomes a row of its own. An item with nothing drawn yet is
rendered at its middle z-slice and first time point, what the viewer opens
on. The predictions come back as the microscopy answer, with each ROI's
`z` and `t`. Cell classifications refer to a label image, not to a shape,
and are not trained on.

A `geo_annotation` scheme's features train the detection and segmentation
trainers on the item's raster basemap:

- **GeoTIFF:** the transform comes from the file's own tags: ModelPixelScale
  with ModelTiepoint, or ModelTransformation, and the EPSG code in its
  GeoKey directory. A projected GeoTIFF is reprojected with pyproj.
- **Image with an extent:** the image is placed in longitude and latitude,
  as the map shows it.

Polygons, rectangles, lines and points become shapes on the raster. A
polygon's holes are filled: the image tools have no polygons with holes. A
GeoTIFF that marks its raster as PixelIsPoint is placed half a pixel over,
as its tiepoint is a pixel's centre; one with a user-defined coordinate
system (EPSG code 32767) cannot be reprojected and its items are left out. The
predictions come back as GeoJSON in EPSG:4326, with each feature marked
`source: model`. On the map they are suggestions, like `preannotation_field`:
they count as an answer only when the annotator edits one or accepts them.
Deleting every suggestion is saved as an empty answer, so they do not come
back.

A map whose basemap is tiles from a server, or only a GeoJSON outline, has
no raster to train on, and its items are left out with a warning. So is a
`classify_region` answer, a label on an outlined region rather than a shape.

### Spectrograms

A `spectrogram_annotation` scheme's boxes train `torchvision-detect` and
`ultralytics-detect`. Each recording is rendered as a spectrogram image the
way the widget draws it: frequency on a linear axis from the scheme's
`min_freq` at the bottom to `max_freq` (or half the sample rate) at the top,
`fft_size` samples per frame, log magnitude, 256 pixels high and 100 pixels
per second. Each box becomes an image box on it; a box with no frequency
range covers the whole band. A box is cut to the recording's length, and one
wholly past its end is left out. Time and frequency map linearly to the image's
pixels, so a box's IoU on the image is its IoU in seconds by hertz, and the
held-out mAP is the same in either.

A recording of 41 seconds or more is an image at least 4,096 pixels wide,
which [tiling](#whole-slides-and-other-large-images) cuts into windows and
stitches back. The predictions come back as boxes in `start_s`, `end_s`,
`low_hz` and `high_hz`, marked `source: ai` with the run's model version,
and prefill the widget.

The recording must be a local file that soundfile reads (WAV, FLAC, OGG and,
with a recent libsndfile, MP3). An item whose audio is a URL is left out with
a warning.

### `llm-sft`

`llm-sft` fine-tunes an LLM on what annotators wrote in a `text` scheme: a
summary, a rewrite, a rationale, a correction. Each labelled item is one
example. The prompt is the scheme's `description` (the question annotators
were shown) followed by the item's text, and the target is the answer. The
loss covers only the answer's tokens. A LoRA adapter is trained by default.
Default model: `Qwen/Qwen2.5-0.5B-Instruct`.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `Qwen/Qwen2.5-0.5B-Instruct` | A causal language model. |
| `lora` | `true` | `false` trains every weight, which needs several times the memory. `{quantize: 4bit}` loads the base model in 4 bits ([QLoRA](#qlora-4-bit-base-weights)). |
| `epochs` | 3 | |
| `batch_size` | 4 | |
| `gradient_accumulation` | 4 | |
| `learning_rate` | 2e-4 with LoRA, 1e-5 without | |
| `max_length` | 1024 | Tokens per example. A long prompt loses tokens from its start; the answer is kept. |
| `max_new_tokens` | 256 | Longest generated answer. |
| `instruction` | the scheme's `description` | Put before each item's text. |
| `system_prompt` | none | |
| `chat_template` | `auto` | `auto` prompts through the tokenizer's chat template when it has one (instruct models), `always` or `never`. |
| `gradient_checkpointing` | `false` | Saves activation memory for about a third more time. |
| `patience` | 1 | Epochs without a lower val loss before stopping. |
| `weight_decay`, `warmup_ratio` | 0, 0.05 | |
| `precision` | `auto` | As in [Parameters](#parameters). |
| `min_instances` | 20 | |

For a `trajectory_edit` scheme, the prompt is the task and the agent's
original steps, and the target is the steps as the annotator corrected them,
so the model learns to repair a trace. Traces nobody edited are left out.
Each step is written as `Step N` followed by its fields (`action: ...`,
`thought: ...`), and the final answer follows the last step when the scheme
has `final_answer_key`.

The checkpoint kept is the one with the lowest val loss. Predictions are
generated greedily for the val, test and unlabelled items. A prediction's
confidence is the model's mean probability for the tokens it generated, which
is what the review queue sorts by. On a GPU with bf16 the model is loaded in
bf16: an 8B model takes 16 GB that way and 32 GB in fp32.

With several annotators, each item keeps one answer, the one `aggregation`
resolves to. The aggregators compare answers word for word: `majority` keeps
the most common answer, and `consensus` keeps the answer of the annotator it
rates most reliable, a rating made from the few answers that do match. Free
text rarely matches word for word, so neither choice says much about which
answer is better.

### `llm-dpo`

`llm-dpo` trains an LLM on which of two responses annotators preferred, by
Direct Preference Optimization (Rafailov et al., 2023), for a `pairwise`
scheme in `binary` mode. Each item answered A or B is one example: the
responses are the scheme's `items_key` list in data order (A is the first),
and the prompt is the item's `prompt` field, or the first of `question`,
`instruction`, `query`, `input` and `context` that the item has. Items
answered with the tie option are left out, since they say nothing about which
response is better. DPO raises the likelihood of the preferred response
relative to the other one, measured against a frozen reference copy of the
starting model; `beta` limits how far the model may move from that reference.

A `trajectory_edit` scheme gives the same three parts without a choice:
the task is the prompt, the corrected steps are the preferred response, and
the original steps the other one. Traces nobody edited are left out. A
prediction says whether the model prefers the correction (`A`) or the
original (`B`), and is made only for held-out traces that have a correction.

A LoRA adapter is trained by default. The reference is then the same model
with the adapter switched off, so no second copy is held in memory.
`lora: false` trains every weight and keeps a frozen copy as the reference,
which doubles the memory. Default model: `Qwen/Qwen2.5-0.5B-Instruct`.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `Qwen/Qwen2.5-0.5B-Instruct` | A causal language model. |
| `lora` | `true` | |
| `beta` | 0.1 | Lower lets the model move further from the reference. |
| `epochs` | 2 | |
| `batch_size` | 4 | Preference pairs per step. |
| `gradient_accumulation` | 4 | |
| `learning_rate` | 5e-5 with LoRA, 5e-7 without | |
| `max_length` | 1024 | Tokens per prompt and response. |
| `instruction` | none | Put before each item's prompt. |
| `system_prompt`, `chat_template`, `gradient_checkpointing` | as for `llm-sft` | |
| `patience` | 1 | Epochs without a lower val DPO loss before stopping. |
| `weight_decay`, `warmup_ratio` | 0, 0.1 | |
| `precision` | `auto` | As in [Parameters](#parameters). |
| `min_instances` | 20 | |

The checkpoint kept is the one with the lowest DPO loss on val, and the run
log reports how often the model prefers the annotators' choice on val. A
prediction is the response the trained model prefers, with the probability of
that preference as its confidence. As a prelabel, the preferred response's
card is selected when the annotator opens the item. With `randomize_order`,
the selection follows the response to wherever this annotator sees it. The
saved adapter generates text and loads with peft like any other adapter.

### Agent traces

A `trajectory_edit` prediction has no prelabel display: the widget starts
from the agent's original trace. Its predictions are stored and scored, and
the server does not start with the scheme in `writeback.schemas`, since
nobody would see its prelabels. The held-out score is `closer_to_correction`: for
`llm-dpo`, the share of held-out traces where the model prefers the
correction; for `llm-sft`, the share where the written steps are closer, by
token F1, to the correction than to the original (`token_f1` against the
correction is reported beside it).

### `prm-reward`

`prm-reward` trains a process reward model on a `process_reward` scheme:
annotators rate each step of a trace correct, neutral or wrong, or click the
first wrong step. The trace is one input, the task followed by `Step 1`,
`Step 2` and so on, and a transformer encoder learns a three-way rating at
each step's last token, so each rating is made with the steps before it in
view. Steps nobody rated are left out of the loss. Default model:
`answerdotai/ModernBERT-base`, chosen for its 8,192-token context.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `answerdotai/ModernBERT-base` | An encoder with a fast tokenizer. |
| `max_length` | 1024 | Tokens per trace. Steps past it are neither trained on nor rated, and the run log counts them. |
| `epochs` | 6 | |
| `batch_size` | 8 | Traces per step. |
| `learning_rate` | 5e-5, or 3e-4 with LoRA | |
| `lora` | none | |
| `patience` | 2 | Epochs without a higher val step macro-F1 before stopping. |
| `weight_decay`, `warmup_ratio`, `precision`, `min_instances` | 0.01, 0.1, `auto`, 20 | |

The held-out score is `step_macro_f1`, macro-F1 over the three ratings on
every rated step; most steps in most traces are correct, so accuracy would
flatter a model that never says "wrong". The run also reports
`step_accuracy` and `first_error_accuracy`, the share of traces where the
model's first wrong step is the annotators' first wrong step.

A prediction rates every step that fits in `max_length`, with the
probability of each rating as its confidence and the least confident step as
the trace's. With the scheme in `writeback.schemas` and `ai_prelabel: true`
on the scheme, the "AI pre-label steps" button offers the trained ratings for
the annotator to verify, ahead of the LLM judge, which is not called for an
item that has them:

```yaml
annotation_schemes:
  - annotation_type: process_reward
    name: step_quality
    description: Rate each step
    steps_key: steps
    ai_prelabel: true

model_training:
  enabled: true
  writeback:
    schemas: [step_quality]
    include_unlabeled: true
```

### `reward-model`

A scalar reward model: a transformer with one output, trained so that the
response annotators preferred scores higher. `llm-dpo` trains a policy from
preferences; this trains the reward model itself, for RLHF, best-of-n
sampling or ranking new outputs. It learns from every comparative type:

| Scheme | Training signal |
|---|---|
| `pairwise`, `binary` | The chosen response beats the other. Ties are skipped. |
| `pairwise`, `scale` | The side the slider leans to wins, weighted by how far it leans (a full push weighs 1). The midpoint is skipped. |
| `ranking` | The whole order, by the Plackett-Luce loss. `ranking_loss: pairs` uses Bradley-Terry over every pair in it instead. A ranking with a tie (`allow_ties`, stored as `B,D=A,C`) trains on its pairs, and tied items are not compared with each other. The bundle keeps the order as stored, so its targets contain tier strings such as `D=A`; the trainer splits them. |
| `bws` | The best item beats every other item in the tuple, and every other item beats the worst. |

The loss is Bradley-Terry, `-log sigmoid(r_winner - r_loser)`, the
reward-modelling loss of InstructGPT. When an item has a prompt (`prompt`,
`question`, `instruction`, `query`, `input` or `context`), each reward is of
the response given the prompt. A ranking's options are the scheme's labels,
each scored given the item's text.

Predictions answer the scheme's own question, so they are scored and written
back like any other: the preferred letter (with confidence
`sigmoid(|r_A - r_B|)`), a point on the scale, the order, or the best and
worst. Every prediction also carries the `rewards` it came from. Only
differences between rewards are meaningful.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `distilbert/distilroberta-base` | An encoder, or an LLM with `lora`. |
| `ranking_loss` | `plackett_luce` | `ranking` only: `plackett_luce` or `pairs`. |
| `max_length` | 512 | Tokens per scored text, prompt and response together. |
| `batch_size` | 8 | Comparisons per step. |

It also takes the parameters in [Parameters](#parameters), including `lora`
with `quantize`. BWS tuples are built by the server from `bws_config`. A run
from the server's own data has them; the tuples are not in the data files.

### `hf-relation`

For `span_link`, `event_annotation` and `coreference` schemes, whose answers
are links between the spans of the scheme named by `span_schema`. One
transformer encoder and three small heads, trained together:

- a **mention tagger**, BIO tags over tokens for the spans annotators drew;
- a **pair classifier** over two spans (the encoder states at each span's
  first and last token, and their product): `none` or a link type for
  relations, `none` or a role for a trigger and an argument, same entity or
  not for coreference;
- a **span classifier**: each span's event type (or `none`), which picks out
  the triggers, and for coreference the entity type of a span's chain.

Pairs are trained on the annotators' spans and predicted on the spans the
tagger finds, so the held-out score measures the whole pipeline: a link
counts only when both of its spans were found with the right boundaries.
Coreference is decoded by mention ranking: each mention joins its most
likely earlier mention, when that is more likely than not. An item counts
as labelled when its annotator drew spans in the `span_schema`; one with
spans and no links trains as "nothing linked here".

| Kind | Held-out metrics | Headline |
|---|---|---|
| `span_link` | link precision, recall and F1 over (span offsets, type); mention F1 | F1 |
| `event_annotation` | trigger F1 over (offsets, event type); argument F1 over (trigger, event type, argument offsets, role) | argument F1 |
| `coreference` | MUC, B-cubed and entity CEAF F1; CoNLL F1, their mean | CoNLL F1 |

For coreference, a mention annotators placed in no chain is a singleton.

**Dependency parsing.** Potato stores a dependency parse as a span scheme
plus a `span_link` scheme with directed link types, each link from the head
to the dependent (see `demo/13-dependency-tree`). When every training answer
is a tree (one link fewer than spans, no span with two heads), the run
decodes trees: the span classifier scores each span as the root, the pair
classifier scores each possible head, and the parse is the maximum spanning
tree over those scores (Chu-Liu-Edmonds), so every prediction is one tree.
The held-out score adds `uas` and `las` when every training answer is a
tree, whatever the held-out items look like. `decode: pairs` turns tree
decoding off (the scores then measure the heads the pair classifier picked),
and `decode: tree` refuses a run whose answers are not trees.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `distilbert/distilroberta-base` | A Hugging Face encoder. |
| `max_length` | 512 | Tokens per item. Spans past the cut are not trained on or predicted; the run log counts them. |
| `max_negatives` | 100 | Unlinked span pairs trained on per item, sampled. |
| `decode` | `auto` | `auto`, `tree` or `pairs`; see above. |
| `epochs` | 10 | |
| `patience` | 3 | |

The prelabel is the spans and the links, chains or events between them. See
[Write-back](#write-back) for how the page shows them.

### `hf-conversation-tree`

For `tree_annotation` schemes, where annotators answer a question about each
turn of a conversation tree (`node_scheme`) and select the best path by
clicking nodes. One encoder reads each turn with its parent's text as
context; a node head predicts the answer to each node question, and a path
head predicts whether a turn continues the selected path from its parent,
trained on the path's turns against their siblings. A predicted path starts
at the root and takes the child the path head scores highest, while that
score is above 0.5.

Turns annotators did not answer are left out of training, not treated as
answered "none". The tree is read from the item field of the
`conversation_tree` display. Held-out metrics are node-answer accuracy and
macro-F1 (the headline) and `path_accuracy`, how often the whole selected
path is right. It takes `model_name` (default
`distilbert/distilroberta-base`), `max_length` (default 256, per turn and its
parent) and the parameters in [Parameters](#parameters).

### `byt5-gloss`

For `interlinear_gloss` schemes. Fine-tunes ByT5 (`google/byt5-small` by
default), a byte-level model: glossing data is small and its words are rare,
and a byte model can still read a word it has never seen. One model learns
two tasks, told apart by a prefix: a word's segmentation (with the word and
its sentence) to its gloss line, and, when annotators segmented words, a word
to its segmentation.

A prediction starts from the words the page shows and any segmentation the
item pre-fills (`morphemes_field`). A word with no segmentation is segmented
first, then glossed. Held-out metrics are word gloss accuracy and morpheme
gloss accuracy (the headline): each gold morpheme gloss matched at its
position, as in the [gloss agreement report](../annotation-types/text/interlinear_gloss.md).

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `google/byt5-small` | A seq2seq model. |
| `epochs` | 20 | |
| `max_length` | 256 | Bytes of input per word (word, segmentation and sentence). |
| `max_new_tokens` | 64 | Longest gloss or segmentation generated, in bytes. |
| `min_instances` | 10 | Glossed sentences in the train split. |

The prelabel fills the gloss grid. As with the item's own `gloss_field`
prefill, it is saved as the annotator's answer when they move on to the next
item, whether or not they edited it; nothing is saved before that.

### `label-studio-ml`

`label-studio-ml` uses a Label Studio ML backend that is already running,
instead of training a model here. It trains nothing: it checks the backend's
`GET /health`, sends the held-out items (and with
`writeback.include_unlabeled` the unlabelled ones) to `POST /predict` in
batches, and turns the regions it returns into prelabels. The run then has
what a trained model's run has: a held-out score against this project's
annotators, write-back, the review queue, and its run id on each prelabel.

```yaml
model_training:
  enabled: true
  trainer_params:
    label-studio-ml:
      url: http://localhost:9090
      # A backend started with BASIC_AUTH_USER and BASIC_AUTH_PASS: the
      # names of variables holding them here, not the values.
      basic_auth_user_env: LS_ML_USER
      basic_auth_pass_env: LS_ML_PASS
      # Images, with the backend on this machine and
      # LOCAL_FILES_DOCUMENT_ROOT set to the task directory there:
      media_url_prefix: /data/local-files/?d=
```

| Parameter | Default | Meaning |
|---|---|---|
| `url` | none | The backend's address. Required. |
| `basic_auth_user_env`, `basic_auth_pass_env` | none | Environment variables holding the backend's `BASIC_AUTH_USER` and `BASIC_AUTH_PASS`. HTTP Basic is the only authentication a stock label-studio-ml backend has. |
| `api_key_env` | none | An environment variable holding a token, sent as `Authorization: Token <value>`, for a backend behind a proxy that wants one. A stock backend answers it with a `500`. Use one of the two schemes, not both. |
| `label_config` | generated | Labeling config XML to send. By default one is generated from the scheme: `Choices` for `radio`, `select` and `multiselect`, `Labels` for `span`, `RectangleLabels` for an `image_annotation` scheme, or `PolygonLabels` when its tools include `polygon` and not `bbox`. |
| `batch_size` | 16 | Items per `/predict` request. |
| `timeout_s` | 60 | Seconds per request. |
| `media_url_prefix` | none | Send an image as the prefix followed by the file's path relative to the task directory (`cats/img1.png`), instead of the training machine's absolute path to it. A `/` goes between them unless the prefix ends in `/` or `=`. An image outside the task directory has no such path, so it is not sent: it gets no prediction, and the run log names how many. |

Without `media_url_prefix`, an image is sent as an absolute path, which
works only for a backend that opens the path itself. A backend built on the
label-studio-ml SDK reads `data.image` as a URL (`get_local_path`) and fails
on a bare path with `MissingSchema`. For one on the same machine, set
`media_url_prefix: /data/local-files/?d=` and start the backend with
`LOCAL_FILES_DOCUMENT_ROOT` set to the task directory. For one elsewhere, serve
the task directory over HTTP and give that server's URL as the prefix.

Text goes to the backend as `data.text` and images as `data.image`. The
results are read with the converter the [Label Studio importer](../tools/import_cli.md)
uses: Label Studio's UTF-16 span offsets become code points, and its percent
coordinates become the image widget's. A prediction's `score` is its
confidence. The backend's own training (its `/webhook` handler) is not
triggered: Potato does not send it annotation events.

### Inference bridges

Four more trainers use a model that runs somewhere else, as
`label-studio-ml` does. Each trains nothing. `fit` checks that the service
answers, and the run sends the held-out items (and, with
`writeback.include_unlabeled`, the unlabelled ones) for predictions. The
predictions get a held-out score against this project's annotators,
write-back and review, like a trained model's. A key is never put in the
config: a parameter names the environment variable that holds it, on the
server, and a value that is not a variable name is refused without being
echoed. When a service's error body repeats the key (an echoed URL or
header), the key is replaced by `[redacted]` before the error is shown. A class name the service uses is mapped to the scheme's labels
through `label_map` (a name mapped to `null` is dropped), then matched exactly
or ignoring case. Shapes come back as the image widget's boxes and polygons,
clipped to the image. Shapes under other labels, and shapes with nothing on
the image, are left out and counted in the run log.

#### `openai-vlm-boxes`

Asks a vision-language model behind an OpenAI-compatible chat API (vLLM,
Ollama, LM Studio, llama.cpp's server, OpenAI) for boxes around the scheme's
labels. Each image is sent as a data URL with a prompt naming the labels, and
the reply is read as JSON `{"objects": [{"label", "box"}]}`. A bare list, a
code fence, and `bbox` or `box_2d` keys are read too.

```yaml
model_training:
  trainer_params:
    openai-vlm-boxes:
      url: http://localhost:8000/v1
      model: Qwen/Qwen2.5-VL-7B-Instruct
      coordinate_format: pixels
```

| Parameter | Default | Meaning |
|---|---|---|
| `url` | required | The API's base URL, ending in `/v1`. |
| `model` | the first the server lists | The model to ask. |
| `api_key_env` | none | Environment variable holding the key, sent as a Bearer token. |
| `prompt` | asks for fractional boxes | The instructions; `{labels}` becomes the scheme's labels. |
| `coordinate_format` | `auto` | `fraction` (0–1), `per_mille` (0–1000) or `pixels` of the image as sent. |
| `box_order` | `auto` | `xyxy` (x0, y0, x1, y1) or `yxyx` (y0, x0, y1, x1). |
| `json_mode` | `schema` | `schema` sends `response_format: json_schema` with the labels as an enum (vLLM and OpenAI honour it), `object` sends `json_object`, `none` sends neither. |
| `max_image_side` | 1280 | The image is shrunk to this longest side before sending; boxes are scaled back. |
| `max_tokens`, `temperature`, `timeout_s` | 1024, 0, 120 | |

Most models answer in their own coordinate convention whatever the prompt
says. Gemma and Gemini give per-mille boxes y first (`[ymin, xmin, ymax,
xmax]`), so with both settings on `auto`, a model whose name contains
`gemma` or `gemini` is read that way. On Gemma 4 12B, a test project of
red and blue squares scored mAP50 0.0 read x first and 1.0 read y first. For other models, `auto` decides once per reply, from all its
boxes: values up to 1.05 (a box drawn to the edge, rounded up) are fractions,
values past the sent image's size are per-mille, and anything else is pixels,
x first.
Qwen2.5-VL answers in pixels: set `coordinate_format: pixels`. The model gives
no score, so its boxes have no confidence. A run in which no reply was JSON
fails.

#### `hf-inference`

Uses a model deployed on Hugging Face: a dedicated Inference Endpoint
(`endpoint_url`) or a model id on the serverless Inference API (`model`). The
task follows the scheme: text classification for `radio`, `select` and
`multiselect` (the top label, or every label scoring at least `threshold`),
token classification for `span` (entities grouped by
`aggregation_strategy`, with character offsets; a `B-`/`I-` tag prefix is
dropped when the full name matches no label), and object detection for
`image_annotation` (boxes scoring at least `threshold`). For a single-choice
scheme the model's top label is the answer: when it is a label the scheme
does not have (after `label_map`), the item gets no prediction rather than
the runner-up.

| Parameter | Default | Meaning |
|---|---|---|
| `endpoint_url` | none | An Inference Endpoint's `https://` URL. Give this or `model`, not both. |
| `model` | none | A model id on the serverless API, such as `dslim/bert-base-NER`. |
| `token_env` | `HF_TOKEN` | Environment variable holding the token. |
| `threshold` | 0.5 | Lowest score kept for a `multiselect` label or a box. |
| `aggregation_strategy` | `simple` | `simple`, `first`, `average` or `max`. |
| `label_map` | none | The model's label to the scheme's, as `{"LABEL_1": "positive"}`. |
| `batch_size`, `timeout_s`, `wait_for_model` | 8, 60, true | `wait_for_model` waits while a serverless model loads instead of failing with 503. |

The health check is one real request (a short sentence, or an 8 × 8 image).
The token is read on the server, so these runs are local only.

#### `roboflow`

Uses a Roboflow detection or instance-segmentation model, hosted
(`https://detect.roboflow.com`, or `https://outline.roboflow.com` for
segmentation) or on a self-hosted Roboflow Inference server
(`http://localhost:9001`). Each image is posted to `<url>/<model_id>`.

| Parameter | Default | Meaning |
|---|---|---|
| `model_id` | required | The model as `project/version`, such as `hard-hats/3`. |
| `url` | `https://detect.roboflow.com` | The API or the self-hosted server. |
| `api_key_env` | `ROBOFLOW_API_KEY` | Environment variable holding the API key. Required. |
| `confidence`, `overlap` | 0.4, 0.3 | Sent to the API as percentages: the lowest confidence returned, and the overlap at which it merges boxes. |
| `shapes` | `auto` | `box`, `polygon`, or `auto`: an outline where the model gives one and the scheme has a polygon tool, else a box. |
| `label_map`, `timeout_s` | none, 60 | |

Roboflow's API takes the key in the query string. Potato does not write
that URL to the run log or an error message, and scrubs the key from an
error body that echoes the request. The health check posts an 8 × 8 white
image, which counts against the account's usage. These runs are local only.

#### `cvat-nuclio`

Uses a CVAT serverless detector, a Nuclio function from `cvat/serverless`
(YOLO, Detectron2 and others), by its URL (`nuctl get functions` lists its
port). Each image is posted as `{"image": <base64>, "threshold": t}`.
`rectangle` shapes become boxes, and `polygon` shapes become polygons, or
their bounding boxes on a scheme with no polygon tool. `mask` shapes are left
out and counted.

| Parameter | Default | Meaning |
|---|---|---|
| `url` | required | The function's address, such as `http://localhost:32768`. |
| `threshold` | 0.5 | Sent to the function, which drops shapes scoring lower. |
| `label_map`, `timeout_s` | none, 120 | |

### `torchvision-detect`

`torchvision-detect` fine-tunes a torchvision Faster R-CNN on the shapes of an
`image_annotation` scheme, starting from torchvision's COCO weights with a new
box head for the scheme's labels. Every shape trains as its bounding box, so a
polygon or mask study trains a box detector. Predicted boxes are written back
as editable boxes in the image widget, marked as model output with the
detector's score.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `fasterrcnn_mobilenet_v3_large_fpn` | Also `fasterrcnn_mobilenet_v3_large_320_fpn`, `fasterrcnn_resnet50_fpn` and `fasterrcnn_resnet50_fpn_v2` (slower and more accurate). |
| `pretrained` | `true` | Start from the COCO weights, downloaded once into torch's cache. |
| `epochs` | 15 | |
| `batch_size` | 4 | Images per step. |
| `learning_rate` | 1e-4 | |
| `gradient_accumulation` | 1 | |
| `weight_decay`, `warmup_ratio` | 1e-4, 0.1 | |
| `patience` | 4 | Epochs without a better val mAP before stopping. |
| `flip` | `true` | Random horizontal flips in training. |
| `min_size` | the architecture's | Shorter image side the detector resizes to. |
| `score_threshold` | 0.25 | Detections below this score are dropped. |
| `max_detections` | 100 | Most boxes per image. |
| `min_instances` | 20 | Annotated images needed in the train split. |

On a Mac it trains on the CPU, not on Metal (`mps`): at the default image
size, one training step on Metal took longer than an epoch on the CPU. Images
are read as [Image items](#image-items) describes.
Only images with at least one box are trained on, for the same
reason as spans: an image with no boxes looks the same as one nobody looked
at. The exception is a tile of an annotated slide; see
[Whole slides](#whole-slides-and-other-large-images). With several annotators, an image's boxes are one annotator's answer,
the one `aggregation` resolves to: the aggregators compare whole answers, and
two people's boxes rarely match exactly.

### `ultralytics-detect`

`ultralytics-detect` trains a YOLO detector with Ultralytics, from a
COCO-pretrained checkpoint. It is faster than `torchvision-detect` to train
and to run. Like it, every shape trains as its bounding box, and predictions
are written back as editable boxes.

**Ultralytics is AGPL-3.0.** A model trained and distributed with it carries
the AGPL's terms, and Ultralytics sells a separate licence for closed use. It
is in none of Potato's extras, so `pip install ultralytics` is a separate
step. Before a run, the Training page asks for confirmation; an API run needs
`accept_licence: true`, and an automatic retrain needs
`auto_retrain.accept_licence: true`. Without it, the run is refused with
"ultralytics-detect is licensed AGPL-3.0".

During a run, the trainer turns off Ultralytics' usage analytics, Ultralytics
HUB, its logging to MLflow, Comet, ClearML, DVC, Neptune, W&B, Ray Tune or
TensorBoard when one is installed, and its automatic installs of packages. These settings are changed in memory only,
for the run's process; the user's Ultralytics settings file is not changed.
Checkpoints download into `~/.cache/potato/ultralytics`.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `yolo11n.pt` | An Ultralytics checkpoint (`yolo11s.pt`, `yolov8m.pt`, ...), a local `.pt`, or an architecture such as `yolo11n.yaml` to train from scratch. |
| `epochs` | 50 | |
| `batch_size` | 16 | |
| `image_size` | 640 | Training and prediction size in pixels. |
| `learning_rate` | Ultralytics' default | |
| `patience` | 10 | Epochs without a better val score before stopping. |
| `flip`, `mosaic` | `true` | Augmentations. |
| `score_threshold` | 0.25 | |
| `max_detections` | 100 | |
| `min_instances` | 20 | |

Ultralytics keeps the checkpoint it scores best on val. The YOLO dataset it
trains on is written into the run directory and deleted afterwards, along with
Ultralytics' own run directory; the artifacts are the best checkpoint and
`results.csv`.

### `torchvision-segment`

`torchvision-segment` trains a torchvision Mask R-CNN, from its COCO weights,
on the outlines of an `image_annotation` scheme: polygons, ellipses, freeform
outlines and brush masks. Boxes are left out, because a box does not say which
pixels belong to the object. Each predicted mask is traced into a polygon and
simplified to within about a pixel, with at most 64 vertices, so the prelabel
is a polygon the annotator can edit point by point; where a mask comes out in
pieces, the largest is kept.

It takes the parameters of `torchvision-detect`, with `model_name`
`maskrcnn_resnet50_fpn` (default) or `maskrcnn_resnet50_fpn_v2`, and a
`score_threshold` of 0.5: Mask R-CNN scores its second guesses for an object
at 0.25–0.6, and each would be a shape for the annotator to delete. On a Mac it trains
on the CPU, not on Metal (`mps`). With torch 2.8, one training step on a
256-pixel image took 57 seconds on Metal and 2.3 seconds on the CPU. Use a
GPU server for it.

### `ultralytics-segment`

`ultralytics-segment` is the YOLO counterpart, training an Ultralytics YOLO-seg
model (default `yolo11n-seg.pt`) on the same outlines and predicting polygons
of at most 64 vertices. It has the parameters, the AGPL-3.0 licence, the
licence confirmation and the analytics handling of `ultralytics-detect`.

### `cellpose`

`cellpose` fine-tunes [Cellpose](https://github.com/MouseLand/cellpose) on
the cell or nucleus outlines of an `image_annotation` or `microscopy`
scheme. Each image's outlines become an instance label image, one id per
outline. Predicted masks are traced back into polygons, each with its mean
cell probability as confidence. Cellpose segments without classes, so every
predicted cell gets the `label` parameter, or the scheme's most common label
when that is unset. Train one model per label if the classes look different.

| Parameter | Default | Meaning |
|---|---|---|
| `base_model` | `cyto3` | `cyto3`, `nuclei` or `cyto2` with Cellpose 3; `cpsam` with Cellpose 4; or a path to your own model. |
| `epochs` | 100 | |
| `learning_rate` | 1e-5 | |
| `weight_decay` | 0.1 | |
| `batch_size` | 8 | |
| `diameter` | none | Typical cell diameter in pixels at prediction; unset lets Cellpose estimate it. |
| `label` | none | Label for every predicted cell. |
| `min_instances` | 5 | Annotated images needed in the train split. |
| `min_train_masks` | 1 | Images with fewer outlines are skipped. |

Install it with `pip install cellpose`; it is in none of Potato's extras.
Both Cellpose 3 and Cellpose 4 work: the trainer passes only the arguments
the installed version accepts. Cellpose's code is BSD-3-Clause; its weights
come from the Cellpose authors under their terms.

### `sam-finetune`

`sam-finetune` fine-tunes Segment Anything's mask decoder to turn a box into
the outline the study's annotators would draw. It trains on the outlines of
an `image_annotation` scheme, each prompted with its bounding box (moved and
resized by up to `box_jitter` of its size, so it learns from boxes as loose
as a detector's). The image encoder stays frozen, and each image's
embedding is computed once.

It refines boxes, so it needs boxes to start from:

- On an item that already carries box prelabels, such as a
  `torchvision-detect` or `ultralytics-detect` run's write-back, each box
  becomes a polygon prelabel.
- On a held-out item, the annotators' own boxes are the prompts, and the
  held-out score measures how close the outline is when the box is right.
  These predictions are scored but never stored or published, because they
  are made from another annotator's answer. The write-back report counts
  them in `n_skipped_heldout_only`.

So the usual sequence is a detection run with write-back on, with
`include_unlabeled: true`, then a `sam-finetune` run on the same scheme.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `facebook/sam-vit-base` | Also `facebook/sam-vit-large` and `-huge`, or a local directory. |
| `epochs` | 10 | |
| `batch_size` | 8 | Boxes per step. |
| `learning_rate` | 1e-4 | |
| `box_jitter` | 0.05 | |
| `mask_threshold` | 0 | Logit above which a pixel is inside. |
| `patience` | 3 | Epochs without a better val mask IoU before stopping. |
| `min_instances` | 10 | Annotated outlines needed in the train split. |

The val split's mean mask IoU is reported as `val_mask_iou`. The SAM weights
are Apache-2.0. The fine-tuned decoder is for prelabels: the image tool's
browser SAM runs separate ONNX weights, and this run does not replace them.

### `layoutlmv3`

`layoutlmv3` fine-tunes LayoutLMv3 for document layout: the regions of an
`image_annotation` scheme drawn on page images (title, table, total, and so
on), learned from the page's words and their positions. Potato runs no OCR,
so each item needs its words:

```json
{"id": "page_001", "image": "pages/page_001.png",
 "words": [{"text": "INVOICE", "bbox": [40, 52, 180, 82]},
           {"text": "Total", "bbox": [300, 700, 380, 730]}]}
```

`bbox` is `[x0, y0, x1, y1]` in the page image's pixels, or from 0 to 1. A
[PAGE XML import](../tools/import_cli.md) in `regions` mode fills
`words` from the file's `Word` elements, or its text lines when it has no
words. Words from a PDF's text layer or another OCR tool work the same way.

Each word is labelled by the region its centre falls in (the smallest one
when regions nest), as BIO tags, so two neighbouring regions with the same
label stay two. Predicted words are merged back into regions, and each region
becomes a box prelabel around its words, with the words' mean probability
as confidence. Held-out scores are box mAP against the annotated regions.
Regions drawn much larger than their words score lower than the model's
boxes deserve, since a predicted box ends at the words.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `microsoft/layoutlmv3-base` | Or `-large`. |
| `epochs` | 10 | |
| `batch_size` | 2 | Pages per step. |
| `learning_rate` | 2e-5 | |
| `max_length` | 512 | Tokens per page; words past it are not trained on or predicted. |
| `min_instances` | 10 | Annotated pages with words needed in the train split. |

**The LayoutLMv3 weights are CC BY-NC-SA 4.0**, not for commercial use. As
with the YOLO trainers, the Training page asks for confirmation before a run,
an API run needs `accept_licence: true`, and an automatic retrain needs
`auto_retrain.accept_licence: true`.

### `vlm-sft`

`vlm-sft` fine-tunes a vision-language model on answers about images. Each
answer becomes an image, a prompt and the answer to learn:

| Scheme | One example per | Prompt | Answer |
|---|---|---|---|
| `text` on image items | item | The scheme's description (or `instruction`), and the item's text if it has any beside the image. | What the annotator wrote. |
| `region_caption` | captioned region | The image with the region drawn as a red box, and the box's coordinates. | The caption. |
| `grounding_eval` | answered expression | The expression, asking for JSON. | `{"bbox": [x0, y0, x1, y1]}`, `{"point": [x, y]}` with `region_type: point`, or `{"absent": true}`. |
| `gui_trajectory` | step judged `correct` that has a click | The screenshot and the step's action text. | The agent's click, `{"point": [x, y]}`. |

Coordinates are on a 0–1000 grid of the image, so any checkpoint can learn
the format from the examples. An answer that does not parse is scored as a
miss. A GUI step judged wrong is not trained on, since nobody marked where
the right click was.

What it predicts:

- **Text:** the generated answer, as a text prelabel.
- **Grounding:** a region or an absence for every expression on the item,
  published as the grounding answer.
- **GUI trajectories:** the model's own click for each step with one, and a
  verdict suggestion: `correct` when it is within `click_radius` of the
  agent's click, otherwise `wrong_element`. The confidence grows with the
  distance from that radius.
- **Captions:** one for each region the annotators drew. These are
  scored but not stored or published, since the regions are an annotator's
  answer. A caption run is for the held-out score and for the model itself.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `Qwen/Qwen2.5-VL-3B-Instruct` | Any image-text-to-text model on the Hub (Qwen2.5-VL, Qwen3-VL, SmolVLM, LLaVA, ...) or a local path. |
| `lora` | on, attention projections | `false` fine-tunes every weight; `{quantize: 4bit}` is [QLoRA](#qlora-4-bit-base-weights). |
| `epochs` | 3 | |
| `batch_size` | 2 | |
| `gradient_accumulation` | 4 | |
| `learning_rate` | 1e-4 with LoRA, 1e-5 without | |
| `max_new_tokens` | 64 | |
| `max_image_side` | 896 | Images are shrunk to this longer side; larger images cost more tokens. |
| `instruction` | the scheme's description | The question, for text answers. |
| `click_radius` | 0.05 | Share of the screenshot within which two clicks count as the same. |
| `gradient_checkpointing` | `false` | |
| `min_instances` | 10 | Training examples needed. |

Real checkpoints need a GPU. A 2B model trains on a Mac's Metal GPU: two
epochs of `Qwen/Qwen3-VL-2B-Instruct` with LoRA over 26 images took 46
seconds. Check the licence of the model you pick: they vary, and
Qwen2.5-VL-3B carries the Qwen research licence while the 7B model is
Apache-2.0.

Qwen-VL models compute part of their vision input with an op that torch
compiles on the GPU when it first runs. On a machine whose NVRTC library does
not match torch's CUDA, the run stops at validation with "torch cannot compile
GPU kernels on this machine" and the package to install. When the library is
installed but in a folder the loader does not search (pip puts it under
`site-packages/nvidia/`), the message names that folder to add to
`LD_LIBRARY_PATH`, which a backend sets in its `env`.

### `hf-audio-tagger`

`hf-audio-tagger` tags labelled time segments for an `audio_annotation`
scheme, such as speech, music, calls or coughs. It fine-tunes a speech encoder that
`AutoModelForAudioFrameClassification` loads (wav2vec 2.0, WavLM, UniSpeech-SAT,
Data2Vec audio) to say which labels are active in each frame of about 20 ms.
Each label is scored separately, so overlapping segments with different labels are learned as
annotated. Predicted segments are written back as editable regions on the
waveform. Default model: `facebook/wav2vec2-base`.

| Parameter | Default | Meaning |
|---|---|---|
| `window_s` | 10 | Seconds of audio per training and prediction window. |
| `threshold` | 0.5 | Frame probability at which a label is active. |
| `min_gap_s` | 0.1 | A gap this short inside a segment is closed. |
| `min_duration_s` | 0.1 | Shorter predicted segments are dropped. |
| `freeze_feature_encoder` | `true` | Keep the convolutional feature encoder fixed. |
| `epochs` | 10 | |
| `batch_size` | 8 | Windows per step. |
| `learning_rate` | 5e-5, or 5e-4 with LoRA | |
| `patience` | 3 | |
| `min_instances` | 10 | Recordings needed in the train split. |

Recordings are read from disk with soundfile (WAV, FLAC, OGG and, with a
recent libsndfile, MP3), mixed to mono and resampled to the model's rate. A
stretch of a recording that no annotator marked counts as "no label here".
That suits a study where annotators mark every event; where they mark only
some, the model learns to miss the rest.

### `whisper-asr`

`whisper-asr` fine-tunes [Whisper](https://huggingface.co/openai/whisper-small)
on the turns annotators corrected in a `speech_transcript` scheme. Each
corrected turn is one example: its audio, cut from the recording by the
turn's start and end, and the corrected text. A turn nobody corrected is not
an example: the scheme saves only the turns an annotator touched, so an
untouched turn may be right or may be unread. A turn flagged with an error
type and no correction is not an example either.

Prediction transcribes every turn of every held-out and unlabelled item. A
turn whose new text differs from the transcript's is a suggested correction,
in the scheme's own shape (`errors: ["asr_error"]` and the new text), with
the model's mean token probability as its confidence. The suggestions
prefill the correction boxes.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `openai/whisper-small` | Any Whisper checkpoint (`-tiny` to `-large-v3-turbo`), or a local path. |
| `language` | unset | The recordings' language (`en`, `fr`, ...). Unset, a multilingual Whisper detects it once, from up to 16 training turns spread over the train split, and the run uses that language for training and prediction; the log says which. When fewer than three in four of the sampled turns agree, the log warns; set it then, or train each language's items separately. |
| `epochs` | 5 | |
| `batch_size` | 8 | Turns per step. |
| `learning_rate` | 1e-5, or 1e-4 with LoRA | |
| `lora` | `false` | |
| `max_new_tokens` | 128 | Longest transcription of one turn. |
| `export_ct2` | `true` | Also write a CTranslate2 copy for faster-whisper (needs ctranslate2). |
| `patience` | 2 | Epochs without a better val word accuracy before stopping. |
| `min_instances` | 10 | Corrected turns needed in the train split. |

A turn longer than 30 seconds, Whisper's input window, is left out with a
warning. The recording is the scheme's `audio_key` field (`audio` by default),
or the file the transcript names when the item has none.

With `export_ct2`, the run's artifacts include a `ct2/` folder, an int8
CTranslate2 copy of the selected model. `potato transcripts --transcribe
--asr-model <path to ct2>` transcribes new recordings with it, and so does
WhisperX, which runs the same format:
`whisperx.load_model("<path to ct2>", device, compute_type="int8")`, with
its word alignment and diarization on top.

### `diarization`

`diarization` learns who speaks when, from the speaker turns annotators
corrected: a `tiered_annotation` scheme's speaker tier, or an `audio_annotation`
scheme whose labels are speakers, such as an [RTTM import](../tools/import_cli.md).
The speaker tier is the one named `speaker` or `speakers`; else the one
tier whose name contains "speaker" (a `non-speaker` tier does not count);
else the only tier with labels. When two tiers qualify, or several tiers
have labels and none is named for speakers, the items are left out with a
warning that names the tiers.

It follows the recipe of pyannote's segmentation model without pyannote or
its gated weights. A speech encoder (WavLM by default) with a frame head for
up to `max_speakers` speakers runs on chunks of `chunk_s` seconds. Each
chunk's loss is taken under the best matching of the model's speaker columns
to the chunk's speakers, so each column stands for whichever speaker it is
matched to in that chunk. A name like `SPEAKER_00` refers to different people
in different recordings, so a classifier over names would have no consistent
target.

Prediction runs chunks that overlap by half and links each chunk's speakers
to the ones found so far by their activity in the overlap. A speaker who is
silent through an overlap and speaks again later gets a new name, because
there are no voice embeddings to recognize them by. Speakers are named in
order of first speech: by the scheme's labels when it lists them, then
`SPEAKER_00`, `SPEAKER_01` and so on. The names are local to the recording.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `microsoft/wavlm-base-plus` | A speech encoder: WavLM, wav2vec 2.0, or a local path. |
| `chunk_s` | 10 | Seconds the model sees at once. |
| `max_speakers` | 3 | Most speakers active within one chunk (up to 6). |
| `threshold` | 0.5 | Frame probability at which a speaker is active. |
| `min_gap_s` | 0.2 | A gap this short inside a turn is closed. |
| `min_duration_s` | 0.2 | Shorter turns are dropped. |
| `epochs` | 10 | |
| `batch_size` | 8 | Chunks per step. |
| `learning_rate` | 1e-4 | |
| `patience` | 3 | |
| `min_instances` | 4 | Annotated recordings needed in the train split. |

On an `audio_annotation` scheme, `diarization` is scored by diarization error
rate, which ignores whether a turn is called `Interviewer` or `SPEAKER_01` and
counts whether the speaker changes at the right times. `hf-audio-tagger` on
the same scheme is scored by segment F1.

### `volume-unet`

`volume-unet` segments CT and MR volumes from the masks annotators painted in
a `volume_annotation` scheme. Each volume is read in the canonical voxel order
the widget paints in, its masks become one label per voxel (where two labels
overlap, the later one in the bundle's label order wins, as the NIfTI export
does), and a 3D U-Net in plain torch learns them: three levels, instance norm,
cross-entropy plus soft Dice, on random cubic patches, half of them centred on
a painted voxel so small structures are seen. Intensities are clipped to each
volume's 0.5 and 99.5 percentiles and standardized. Prediction slides the patch
over the whole volume with half-patch overlap and averages the probabilities.
The masks come back in the widget's shape, per label and axial slice, marked
`prefilled_from: model`, and show on the slice views. A box-only answer has no
mask and is not trained on.

| Parameter | Default | Meaning |
|---|---|---|
| `patch` | 64 | Side of the cubic patch in voxels; a multiple of 2 to the power `levels` − 1. |
| `levels` | 3 | Depth of the U-Net (2 to 5). |
| `base_channels` | 16 | Channels at the first level, doubling at each level down. |
| `patches_per_epoch` | 100 | Random patches drawn per epoch. |
| `foreground_share` | 0.5 | Share of patches centred on a painted voxel. |
| `epochs` | 50 | |
| `batch_size` | 2 | Patches per step. |
| `learning_rate` | 3e-4 | |
| `patience` | 10 | Epochs without a better val mean Dice before stopping. |
| `min_instances` | 3 | Annotated volumes needed in the train split. |

It needs torch and nibabel, and pydicom for DICOM series; a NIfTI volume now
loads without pydicom. A volume whose painted shape differs from the file's is
left out with a warning. It uses no MONAI. A full-size CT is a few hundred
patches to predict, so in practice it needs a GPU.

### `external-3d`

`external-3d` detects 3D cuboids in point clouds with a detector you install,
because the ones that work here (OpenPCDet, MMDetection3D) need CUDA operators
compiled on the GPU host. It writes the annotated scans as OpenPCDet's custom
dataset, in the scan's own frame (no camera calibration needed):

- `points/<id>.npy`: float32 `(N, 4)`, x, y, z and intensity (0 when the file has none);
- `labels/<id>.txt`: one line per cuboid, `x y z dx dy dz heading label`, the
  heading being the rotation about +z (pitch and roll are not kept);
- `ImageSets/train.txt`, `val.txt` and `predict.txt`: the ids.

Then it runs `train_command` once and `predict_command` on the held-out and
unlabelled scans, without a shell, with `{dataset}`, `{workdir}` and
`{predictions}` replaced by their paths; other braces in a command are left
as they are. `predict_command` writes `<predictions>/<id>.txt`,
one line per box: `x y z dx dy dz heading label score`. The boxes come back as
`cuboid_3d` objects marked `source: model`. Lines that do not parse or hold
a non-finite number (`nan`, `inf`), labels the scheme does not have, and boxes
with no size are left out and counted. A
georeferenced scan is written relative to its origin and its boxes are shifted
back. Only cuboids are targets, and only single scans, not sequences.

| Parameter | Default | Meaning |
|---|---|---|
| `train_command` | empty | Run in the run's folder. Empty: nothing is trained, and `predict_command` uses a model of your own. |
| `predict_command` | required | Writes `{predictions}/<id>.txt` for the ids in `{dataset}/ImageSets/predict.txt`. |
| `timeout_s` | 86400 | Seconds each command may run. |
| `min_instances` | 1 | Annotated scans needed when `train_command` is set. |

A command that exits non-zero fails the run with the last lines of its output.
Point-cloud prelabels are now checked before the viewer sees them: an object
whose geometry does not parse, a cuboid with no size, and a label the scheme
does not have are left out.

### `video-track`

`video-track` tracks objects in video, for `video_annotation` schemes in
`tracking` or `combined` mode (other modes train as segments). The annotated
tracks are sampled at `frame_fps`: each sampled frame is read with OpenCV, and
each track's box there is interpolated between its keyframes as the widget
draws it, using the box as a fraction of the picture (the canvas-pixel box
depends on the annotator's screen). A torchvision Faster R-CNN, with
`torchvision-detect`'s parameters, is fine-tuned on those frames.

Prediction samples each video at `predict_fps`, detects on each sampled frame,
and links detections into tracks: each frame's detections are matched to the
live tracks of the same label by box overlap with the track's last box (best
one-to-one match, at least `match_iou`); an unmatched detection of at least
`new_track_score` starts a track; a track missed for more than `max_age`
sampled frames ends. Each detection is a keyframe, so the widget interpolates
between them. The tracks prefill the widget, which puts the boxes in its own
canvas pixels when it draws them.

| Parameter | Default | Meaning |
|---|---|---|
| `frame_fps` | 2 | Frames per second sampled from each annotated video to train on. |
| `predict_fps` | `frame_fps` | Frames per second detected on to predict. |
| `match_iou` | 0.3 | Box overlap at which a detection continues a track. |
| `max_age` | 2 | Sampled frames a track may go undetected before it ends. |
| `new_track_score` | 0.5 | Lowest score at which an unmatched detection starts a track. |
| `min_instances` | 2 | Annotated videos needed in the train split. |

The other parameters are `torchvision-detect`'s. OpenCV reads the videos
(`pip install opencv-python`); a codec it cannot read leaves the item out.

### `rdkit-property`

`rdkit-property` answers a question about a molecule: a `radio`, `select`,
`likert` or `slider` scheme over items that show one. The structure is the
input, not the item's text. It comes from the item's `molecule` display field
(SMILES, a molfile, or a `.mol`, `.sdf` or `.smi` file in the task or media
directory), or from a `chemical_structure` scheme on the same item: the
structure annotators drew (the most common drawing when they differ), or the
one the scheme starts from (`prefill_field`) when nobody drew. The bundle
writes each item's structure into its row, and the build warns how many items
have none.

Each molecule becomes a Morgan fingerprint (radius 2 and 2048 bits by default,
the ECFP4 most property models start from) followed by RDKit's 2D descriptors
(weight, logP, TPSA, ring and atom counts and the rest of `Descriptors`),
scaled. A choice or Likert question is fitted with logistic regression or a
random forest. A slider is fitted with ridge regression or a random forest,
and the prediction is rounded to the slider's `step` (1 when the scheme sets
none) and kept inside its range; when the maximum is off the step grid, the
top is the last step under it. A structure RDKit cannot parse is left out of training and gets no
prediction; the run counts them (`n_unparseable`). The text trainers are
offered for these schemes too, because the items' text is still there.

| Parameter | Default | Meaning |
|---|---|---|
| `model` | `logistic` (choices), `ridge` (sliders) | `logistic`, `random_forest` or `ridge`. |
| `radius`, `bits` | 2, 2048 | The Morgan fingerprint. |
| `descriptors` | true | Add the 2D descriptors. |
| `C`, `alpha`, `n_estimators` | 1.0, 1.0, 300 | Logistic regression's inverse regularization, ridge's regularization, trees in a forest. |
| `class_weight` | none | `balanced` weights rare answers up. |
| `min_instances` | 10 | Labelled molecules needed in the train split. |

It needs RDKit (`pip install "potato-annotation[chemistry]"`).

### `peak-cnn`

`peak-cnn` picks peaks on NMR, IR, Raman, UV-Vis and mass spectra, from
`peak_picking` answers. Its input is the spectrum the scheme's
`viewer_field` shows, read by the same readers as the
[spectrum display](../annotation-types/science/spectra.md), with the
item's or the display's `scan`, `index` or `block`. Its target is the peaks
the annotator kept: accepted suggestions and added peaks alike. A rejected
suggestion is a place with no peak, which the target says by having none
there.

Each spectrum is resampled to `length` evenly spaced points and scaled to 0–1
with peaks pointing up (a transmittance spectrum is flipped, as the display
flips it; `peak_direction` is followed). A stick spectrum keeps each line on
its nearest point. A 1D CNN of dilated residual convolutions predicts each
point's chance of being a peak, trained against a Gaussian bump of width
`sigma` at each kept peak. To predict, it keeps points above `threshold` that
are the highest within `min_separation` points, moves each to the spectrum's
own maximum within `snap` points, and maps it back to x. Peak labels and
assignments are not predicted.

| Parameter | Default | Meaning |
|---|---|---|
| `length` | 4096 | Points per resampled spectrum. Raise it when peaks are narrower than 1/`length` of the x range. |
| `width`, `depth` | 32, 10 | Filters per layer, and layers. |
| `sigma` | 2.0 | Width of the target bump, in points. |
| `threshold` | 0.5 | Probability a point needs to be a peak. |
| `min_separation`, `snap` | 4, 3 | In points. |
| `max_peaks` | 80 | Most peaks per spectrum. |
| `tolerance` | 0.5% of the x range | How far, in x units, a predicted peak may be from an annotated one and still match when scored. |
| `epochs`, `batch_size`, `learning_rate`, `patience` | 60, 8, 1e-3, 10 | |
| `min_instances` | 5 | Annotated spectra needed in the train split. |

The predicted peaks show as review suggestions on the spectrum, marked
"model" (see [Write-back](#write-back)).

### `signal-cnn`

`signal-cnn` labels physiological and sensor signals (EEG, ECG, EMG,
accelerometers) from `interval_label` answers. Each recording is read by the
same readers as the [time-series display](../annotation-types/science/time_series.md).
The display's `channels` are used (every channel when it names none, up to
`max_channels`), resampled to `rate` Hz, and each channel is standardized.
Every recording is read with the first training recording's channels, in
that order; a channel a recording lacks is a flat zero.

The scheme's mode sets the task:

- **epoch**: each annotated epoch is one example, classified whole, as sleep
  staging does. Prediction labels every epoch of the recording that is at
  least half there.
- **free**: the recording is labelled sample by sample, with "no label"
  where no interval is, and trained on random `window_s`-second crops.
  Prediction slides over the recording, takes the most likely label for each
  `frame_s` frame, merges runs of one label into intervals, and drops those
  shorter than `min_duration`.

Point events are neither trained nor predicted. The network is a small
InceptionTime: parallel convolutions of three widths and a max-pool branch,
with a residual every three blocks. With `balanced`, the loss is weighted by
inverse label frequency, which rare sleep stages need.

| Parameter | Default | Meaning |
|---|---|---|
| `rate` | 100 | Hz every channel is resampled to. |
| `max_channels` | 16 | Most channels read when the display names none. |
| `width`, `depth` | 16, 6 | Filters per branch, and blocks. |
| `balanced` | true | Weight the loss by inverse label frequency. |
| `window_s`, `windows_per_epoch` | 30, 400 | Free mode: seconds per crop, and crops per epoch. |
| `frame_s`, `min_duration` | 1.0, one frame | Free mode: seconds per predicted frame, and the shortest interval kept. |
| `epochs`, `batch_size`, `learning_rate`, `patience` | 30, 32, 1e-3, 5 | |
| `min_instances` | 3 | Annotated recordings needed in the train split. |

A WFDB record is linked into the bundle with its `.dat` and annotation
files. The predicted intervals cover every channel (`channel: null`) and
show as pre-annotations on the recording (see [Write-back](#write-back)).

### `episode-model`

`episode-model` learns the three layers of an `episode_annotation` answer:
the phases, the outcome and the reward curve. Its input is the episode's
numeric series (joint positions, gripper state, forces: whatever the LeRobot
dataset, HDF5 demo or episode manifest records), one row per frame, each
series standardized. Video is not read. A phase that only looks different
on camera, and is not different in what the robot measured, is not one it
can find.

A convolution over the series feeds a bidirectional GRU and three heads: a
phase per frame (with "no phase" between phases), an outcome per episode
(from the mean of the GRU's states), and a reward per frame. The reward head
is trained only where the annotator drew the curve, because outside it they
said nothing. A layer an answer leaves empty is left out of that episode's
loss, so an episode marked only with an outcome still trains the outcome.
The outcome head trains when the training episodes have at least two
outcomes. Episodes longer than `max_frames` are trained on random crops.

| Parameter | Default | Meaning |
|---|---|---|
| `hidden` | 64 | GRU state size. |
| `max_frames` | 2000 | Longest stretch trained on at once. |
| `phase_weight`, `outcome_weight`, `reward_weight` | 1.0 each | Each head's share of the loss. |
| `reward_points` | 50 | Points in a predicted reward curve. |
| `epochs`, `batch_size`, `learning_rate`, `patience` | 40, 4, 1e-3, 8 | `batch_size` is episodes per step. |
| `min_instances` | 5 | Annotated episodes needed in the train split. |

The prediction is the stored answer's shape: phases in the scheme's taxonomy,
an outcome it offers, and a reward curve inside `reward_range`, only for the
`layers` the scheme shows. It pre-fills the timeline (see
[Write-back](#write-back)). LeRobot datasets need pyarrow and HDF5 demos need
h5py. Rollout evaluation (`rollout_evaluation`) is not trained here: its
preference is between videos, which this model does not read.

### Decision models

A decision model (hosted Jev, OpenJev, `laya-serve`, or Laya in this process)
returns a probability for each option of a question. Potato uses one as a
[labeling engine](../labeling-engine/configuration.md) source with
`kind: decision`, or as a labeling model in solo mode. Three trainers fit
one to the study's labels, for `radio`, `select`, `likert` and `slider`
schemes: `decision-calibrate` adjusts any decision model's probabilities,
`laya-finetune` trains Laya, and `openjev-finetune` trains OpenJev. Each asks
the scheme's question the way the engine asks it. A `slider` is asked as a
rating with one option per position, up to 21 positions.

### `decision-calibrate`

`decision-calibrate` trains nothing. It asks the model the scheme's question
for each labelled item and fits a calibration on the train split. It finds
the model in the config: the `source` parameter names the engine source's
`id`, or `solo_mode` for the first decision model in
`solo_mode.labeling_models`, and `auto` (the default) takes the first one
found.

| Parameter | Default | Meaning |
|---|---|---|
| `source` | `auto` | Which decision model, as above. |
| `method` | `temperature` | `temperature` fits one temperature per question: it changes how confident the model is, never which option it picks. `temperature+bias` also fits an offset per option, which can change the pick when the model under-predicts an option this study uses often; it needs more labelled items per option. |
| `l2` | 0.01 | Keeps the option offsets small. |
| `instructions` | the engine source's `prompt` | Put before the scheme's description in the question. |
| `batch_size` | 16 | Items sent to the model at a time. |
| `max_items` | 2000 | Most items asked in one run, train first: each is one request. |
| `min_instances` | 20 | |

A calibration needs mistakes to learn from. When the model got fewer than two
train items wrong, or the fitted temperature reaches the edge of its range
(0.05 to 20), the run keeps the model's own probabilities, writes
`"fitted": false` and the reason into `calibration.json`, and says so in the
log. Fitted to train items with no mistakes, the temperature would run down
to 0.05 and every later answer would read as certain.

The run log and the run's metrics give accuracy, log loss and expected
calibration error (ECE) before and after, on each split. The result is
`artifacts/calibration.json`. To use it, name it as `calibration` in the engine
source's `options`, or on the solo-mode model:

```yaml
labeling_engine:
  sources:
  - id: openjev
    kind: decision
    endpoint_type: systemone
    base_url: http://gpu-host:3000
    model: openjev
    options:
      calibration: annotation_output/training/runs/<run_id>/artifacts/calibration.json
```

A calibration applies to the question it was fitted for. A question asked with
other instructions, such as a revised solo-mode prompt, can need a new fit.
The run makes one request per item it scores, so `max_items` caps a run
against a hosted model's bill. It runs on the `local` backend only: it
calls the model service this server uses, and the source's API key goes to
the run's process in its environment, never into the run's files. On
another backend the run is refused with `409`.

### `laya-finetune`

`laya-finetune` trains Laya itself (Convai Innovations, Apache-2.0, a
ModernBERT encoder with a decision head) with Laya's own fine-tuning and
temperature calibration. The data is the scheme's question for each labelled
item, with the annotators' answer. The checkpoint in `artifacts/model` loads
wherever Laya does: set `model` of a `laya` engine source or solo-mode model to
that directory.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `convaiinnovations/laya` | A Laya checkpoint: a Hub id, an alias (`multilingual`), or a local directory such as an earlier run's `artifacts/model`. |
| `epochs` | 4 | |
| `micro_batch`, `grad_accum` | 8, 2 | Items per step, and steps per update. |
| `encoder_lr`, `head_lr` | 2.5e-5, 1e-4 | |
| `loss` | `soft-ce` | Or `rlcd`, Laya's notebook objective. |
| `freeze_encoder` | `false` | Train the head only. |
| `shuffle_options` | `true` | Present the options in a random order each epoch, so the model cannot learn a position. |
| `instructions` | the engine source's `prompt` | Put before the scheme's description in the question. |
| `calib_frac` | 0.1 | Share of the train split held back for Laya's calibration. |
| `min_instances` | 20 | |

Laya's training loop runs to the end once it starts, so a cancel takes effect
when the grace period ends and the run's process is stopped.

### `openjev-finetune`

`openjev-finetune` trains OpenJev (`alanhuangya/OpenJev-8B`, Apache-2.0:
Qwen3-8B with a decision head) with `wev train`, from `wev`, the package that
serves it. The Hub release has its LoRA adapter merged into the model, and
`wev train` continues only from a `wev` training run, so the trainer first
converts the release into one: the merged model as the base, a new adapter
that changes nothing until trained, and the released head. Converted, it
matched the release's probabilities on 43 test items (largest difference
0.0). The conversion is cached in
`~/.cache/potato/openjev`, once per model revision. The run then trains on
the scheme's question for each labelled item and reports each epoch's loss
and val accuracy.

| Parameter | Default | Meaning |
|---|---|---|
| `model_name` | `alanhuangya/OpenJev-8B` | An OpenJev release, a local export, or an earlier run's `artifacts/model` to continue from. |
| `epochs` | 3 | |
| `batch_size` | 8 | Items per step. |
| `gradient_accumulation` | 1 | |
| `learning_rate` | 5e-5 | `wev` advises this for models of 4B and up, citing kev's measurement that 2e-4 erodes what the model knows. |
| `gradient_checkpointing` | `true` | |
| `max_state`, `max_branch` | 4096, 2048 | Tokens of item text and of the question; an item that does not fit is left out of training. |
| `instructions` | the engine source's `prompt` | Put before the scheme's description in the question. |
| `min_instances` | 20 | |

The 8B model needs a GPU with about 16 GB free; on a 24 GB card, training on
178 items took about 10 minutes, conversion included. `artifacts/model` is a
`wev` training run of about 190 MB that names the release it started from.
Serve it with `wev serve --model <run>/artifacts/model --port 3000` and use
that server as a `systemone` source (`base_url: http://<host>:3000`). The
model card notes that some of OpenJev's training data is for research only;
check those terms before commercial use. Hosted Jev is a service and cannot
be fine-tuned; `decision-calibrate` fits it to a study.

---

## Held-out scores

Every run scores its own predictions on the val and test items against the
resolved labels, whichever trainer it used. The metrics depend on the
scheme's kind:

| Kind | Metrics | Headline |
|---|---|---|
| `radio`, `select` | accuracy, macro-F1 | macro-F1 |
| `likert` | accuracy, macro-F1, and mean absolute error when the labels are numbers | macro-F1 |
| `multiselect` | micro-F1, macro-F1, exact match | micro-F1 |
| `span` | precision, recall, F1 over spans that match on start, end and label | F1 |
| `text` | exact match, token F1 | token F1 |
| `pairwise` (`binary`) | accuracy, macro-F1, over items not answered as a tie | accuracy |
| `image_annotation` | COCO mAP at IoU 0.5 (`map_50`) and averaged over 0.5–0.95 (`map_50_95`) | `map_50` |
| `audio_annotation` | precision, recall, F1 over segments with the same label at IoU of at least 0.5, and their mean IoU (`matched_iou`) | F1 |
| `slider` | accuracy (the exact position), mean absolute error | accuracy |
| `pairwise` (`scale`) | direction accuracy (the preferred side; a midpoint answer is not counted), mean absolute error on the scale | direction accuracy |
| `ranking` | Kendall's tau, pairwise accuracy (the share of pairs in the annotators' order), top-1 accuracy. A pair the annotators tied is not scored. | Kendall's tau |
| `bws` | best accuracy, worst accuracy, and their mean | best-worst accuracy |
| `soft_label` | 1 − Jensen-Shannon divergence from the annotators' mean distribution, the divergence itself, cross-entropy, argmax accuracy | `distribution_agreement` |
| `span_link`, `event_annotation`, `coreference` | see [`hf-relation`](#hf-relation) | F1, argument F1, CoNLL F1 |
| `interlinear_gloss` | word and morpheme gloss accuracy | morpheme accuracy |
| `tree_annotation` | node-answer accuracy and macro-F1, path accuracy | node macro-F1 |
| `microscopy` | as `image_annotation`, per rendered plane | `map_50` |
| `geo_annotation` | as `image_annotation`, on the raster | `map_50` |
| `region_caption` | token F1 per region (0 for a region with no caption), corpus BLEU-4 | token F1 |
| `grounding_eval` | accuracy at IoU 0.5 (`acc_50`), also at 0.25 and 0.75, mean IoU, and `absent_accuracy`, the share of absent referents declined. With `region_type: point`, `point_in_region`. | acc@0.5, or point-in-region |
| `gui_trajectory` | verdict accuracy and macro-F1 over the judged steps; `click_accuracy`, the share of steps judged `correct` where the model's click is within 5% of the screenshot of the agent's | verdict macro-F1 |
| `speech_transcript` | word and character error rate over the corrected turns (`wer`, `cer`), and the original transcript's WER on the same turns (`wer_asr`). A turn the model left alone is scored as the transcript's text. | `word_accuracy`, 1 − WER (0 at worst) |
| `tiered_annotation` speaker turns, and `audio_annotation` with `diarization` | diarization error rate (`der`): missed speech, false alarm and speaker confusion (each also reported) over the annotated speech, on a 10 ms grid, under the best one-to-one mapping of predicted to annotated speakers. No collar. | `diarization_accuracy`, 1 − DER (0 at worst) |
| `spectrogram_annotation` | as `image_annotation`, on the rendered spectrogram | `map_50` |
| `volume_annotation` | Dice per label per volume (`dice_<label>`) and their mean over every volume and label pair; a label the model left out of a volume that has it scores 0 | `mean_dice` |
| `spatial_annotation` | 3D average precision per label at volumetric IoU 0.5 (`ap_3d_50_<label>`), mean over labels at 0.25 and 0.5, and precision, recall and F1 at 0.5, matching oriented cuboids exactly | `map_3d_50` |
| `video_annotation` (tracking) | MOTA, IDF1, ID switches, misses and false positives at IoU 0.5, on frames sampled at 2 per second across each annotated video | `idf1` |
| `peak_picking` | precision, recall and F1 of peaks matched one to one, nearest first, within the run's `tolerance` (else 0.5% of the spectrum's x range), and the mean offset of the matched ones. A peak predicted on a spectrum the annotator said has none is a false alarm. | F1 |
| `interval_label`, epoch mode | accuracy and macro-F1 over the annotated epochs, each read at its centre | macro-F1 |
| `interval_label`, free mode | precision, recall and F1 over intervals with the same label at IoU 0.5 | `interval_f1` |
| `episode_annotation` | phase accuracy and macro-F1 on a 0.1 s grid (a phase predicted where the annotator marked none is a false alarm), phase segment F1 at IoU 0.5, outcome accuracy, and Pearson's r of the reward curve where it was drawn | `phase_macro_f1`; with no phases, `outcome_accuracy`, then `reward_pearson` |

A classifier trained with `soft_targets` also reports `soft_jsd`,
`soft_cross_entropy` and `ece`; see
[Learning from disagreement](#learning-from-disagreement).

Metric names carry the split (`val_macro_f1`, `test_f1`). An item with a label
and no prediction counts as wrong, so a trainer cannot raise its score by
leaving out the hard items; `<split>_coverage` is the share of items that got
a prediction.

The headline is shown in the Runs table's **Held-out score** column, with the
split and metric in the tooltip, and on the run page. It is the first scheme's headline on the first of val
and test that has items. When the trainer chose its checkpoint on val, test
is tried first, because the trainer has already seen how it scores on val. A
run with no val or test items is "not scored".

Token F1 is the overlap of words between the generated and the written
answer, regardless of order. It credits an answer that uses the right words in
the wrong places, so read it together with exact match.

A detector's boxes are scored against each annotated shape's bounding box,
as COCO's box mAP is: a polygon or mask an annotator drew counts as found
when a predicted box of its label overlaps its bounding box by IoU 0.5. A
segmentation model's polygons are scored against the annotated outlines as
polygons (an ellipse or a mask becomes one), and annotated boxes are left
out, as they are in its training.

The detection headline is mAP at IoU 0.5 rather than COCO's 0.5–0.95 average.
Two annotators' boxes for one object rarely overlap at IoU 0.9, so the
stricter thresholds partly measure how consistently people draw; both numbers
are recorded.

---

## Write-back

After a successful run, its predictions are stored, and the ones that pass
these checks are written into the item's `predictions` field (or
`writeback.field`) as prelabels. The checks run in this order, and each skip is
counted in the run's write-back report (the `writeback` field of
`/admin/training/api/status`):

1. **Train-split items are never prelabelled.** A model is confident about its
   own training data for reasons that say nothing about new data. This covers
   the train split of every run still in the ledger (see `retain_runs`): when
   a run trains on an item, a prelabel an earlier run left on it is taken
   down.
2. **Only schemes in `writeback.schemas`** are published. The list is empty by
   default, so turning training on changes nothing annotators see.
3. **Pairs a reviewer rejected are skipped.** An `(item, scheme)` pair with a
   `reject` verdict in [model review](model_review.md) is not shown again.
   The prelabel comes off the item as soon as the verdict is recorded.
4. **The confidence floor.** Below `min_confidence`, the prediction is stored
   but not published.

Write-back does not change human labels. Predictions go into item data;
annotations live in user state, which write-back does not address.

Prelabels show on the annotation page as a pre-filled answer once
`writeback.schemas` is set: boxes, outlines and audio segments as shapes the
annotator can edit, a pairwise preference as the selected card or the scale's
slider position, a ranking as the list's order, a BWS pick as the selected
best and worst, a soft label as slider positions, a gloss in the gloss grid,
and a conversation tree's node answers and path. No `pre_annotation` block is
needed.

Three types show a prediction as something to review rather than as the
answer:

- **Peaks** (`peak-cnn`) are suggestions on the spectrum, listed with
  "· model". Under the display's `prepick` (`method: auto`, or `true`), the
  item's own `peaks` come first, then the model's, then the file's peak
  table, then the detector. `method: model` shows the model's only. An
  accepted model peak is stored with `source: model`.
- **Intervals** (`signal-cnn`) are pre-annotations on the recording, shown
  dashed and listed with "· from the model". They are used only when the
  file and the item give no intervals of their own: a recording's own
  annotations are someone's labelling, and come first. The file's point
  events stay alongside the model's intervals, since they do not overlap. As with the file's,
  they are saved with the annotator's first change, and `pre_annotations:
  false` on the scheme turns them off.
- **An episode answer** (`episode-model`) pre-fills the timeline's phases,
  outcome and reward curve. It is stored once the annotator edits it.

An annotator held out from machine help (`ai_support.holdout`), or answering
a blind labeling-engine request, sees none of these.

Shapes a widget could not show as they are, which it would repair as it drew
them, are left out of the prelabel: a box with no width, a shape off the
image, a label the scheme does not have, a microscopy ROI on a plane its
image lacks, a GUI verdict the scheme does not offer, a map feature off the
globe. A microscopy prediction shows as ROIs on their planes. A grounding prediction
shows as each expression's region, or as absent. A GUI trajectory
prediction shows as a suggested verdict on each step. A map shows its
prediction as suggested features, which become the answer only when the
annotator edits one or accepts them. A caption run, and a `sam-finetune` run's
predictions on held-out items, are scored but not published (see those
trainers).

A relation, chain or event prediction shows as spans in the `span_schema`
with the links, chains or events drawn between them, while the annotator has
no spans of their own on the item. They can be edited or deleted, and they
are stored as the annotator's answer when the annotator moves on to the next
item. The first edit of any one scheme (a span, a link, a chain or an event)
stores every scheme's prelabels first. Deleting a predicted span also drops
the predicted links and event arguments that use it. Once the annotator has
stored an edit or moved on, the prediction is not offered again, so an item
whose every predicted span was deleted stays empty. If
an enabled `pre_annotation` block is also present, its settings apply instead,
and its `field` must match `writeback.field`; the server refuses to start when
it does not, since no training prelabel would show. A prediction with nothing
in it (no spans, no shapes, no segments) is counted in `n_skipped_empty`, not
written, and one for an item no longer in the data in
`n_skipped_missing_item`. If the annotator leaves a span prelabel unchanged, it is saved as
their answer on Next, the same as for every other type.

A prelabel is not saved while the annotator is only looking at it. It
becomes their answer when they edit it or move on, so an item nobody has
answered does not count as done, and a model's answer does not go back into
training as a human label.

By default a run predicts only on the items in its `val` and `test` splits,
which already have a resolved human label, so items nobody has labelled get no
prediction. Set `writeback.include_unlabeled: true` to predict on those items
too: the run's bundle then carries them as an `unlabeled` file that the model
predicts on but is never trained or scored on, and their predictions pass the
same checks. This is the setting for using prelabels to speed up annotation
(with [model review](model_review.md) serving them least-confident first, or
[`assignment_strategy: llm_confidence`](../advanced/task_assignment.md) for a
study where every item still needs a label).
Prelabels anchor annotators, so turn it on once the held-out score supports
it.

One prediction is kept per item and scheme: a newer run replaces an older
one. At startup, the stored predictions for the schemes in
`writeback.schemas` are written back into item data, so prelabels survive a
restart. The replay applies the same checks as above, so a training item, a
rejected pair or a prediction under the floor stays off after a restart too.

To withdraw a run's prelabels, send `DELETE /admin/training/api/runs/<run_id>/predictions`.
This removes the stored predictions and takes their prelabels off the items.

### Corrections and pinned items always train

Two kinds of item go to the `train` split of every later run, whatever their
place in the stable split:

- **Items a reviewer corrected.** A `correct` verdict in
  [model review](model_review.md), for the run's scheme or for no scheme,
  means a person fixed the model's answer. Corrections come from the items
  the model was worst at, so in `val` or `test` they would score the model
  on a sample of its own mistakes. `accept` and `reject` verdicts do not move an item.
- **Pinned items.** "Train on these" beside a slice on the
  [Catalog](../agent-evaluation/semantic_curation.md) page pins what the slice
  matches, for instance the built-in `model-found-nothing` slice, the items
  the model predicted nothing on. A pinned item trains once someone has
  labelled it; until then the run counts it as waiting.

A run whose bundle moved held-out items into `train` logs a warning saying
how many, because its held-out score is then computed without them and is not
directly comparable with an earlier run's. The counts are in the bundle's
`manifest.json`, under `stats.forced_train`.

### Save a run's split as a dataset version

The run page's "Keep this split as a dataset" saves a run's `val`, `test` or
`train` items, with their agreed human labels, as a new version of a
[dataset](../agent-evaluation/datasets_and_experiments.md). A version does not change afterwards, so
later models, and LLM prompts in the datasets' experiment runner, can be
compared on exactly those items. It needs `datasets.enabled: true`.

The version holds that split and nothing else. Saving into a dataset that
already has versions starts a new version from scratch rather than adding to
the last one. Run 2's `val` items saved over run 1's would otherwise include
items run 2 trained on. Each example's `split` is the run's split name. Its
`inputs` are the item's data without the prelabel field, so an evaluation
cannot read the model's answer, and its `reference_outputs` cover only the
run's schemes. Dataset names cannot contain `/` or `\`, or start with `.`.

### Where a prelabel came from

`GET /admin/model-review` includes `provenance`: for each item in the review
queue whose prelabel a training run wrote, the run id, the trainer and the
run's held-out score, per scheme. Prelabels supplied with the data have no
entry.

---

## Routes

All routes are under `/admin/training` and need admin access (an admin
session, or `X-API-Key`). POST and DELETE requests from a browser must be
same-origin.

| Route | Purpose |
|---|---|
| `GET /admin/training` | The Training page: start a run, the run list, the trainers. |
| `GET /admin/training/runs/<run_id>` | One run: status, metrics, events, the split of each item. |
| `GET /admin/training/api/trainers` | Every trainer, its kinds, modalities, licence and whether it is installed. |
| `GET /admin/training/api/schemas` | The study's schemes, their kind and the trainers that fit each. |
| `GET /admin/training/api/status` | The current or last run: state, step, progress, metrics, warnings, `skip_reason`, `writeback`, and `queue`, the waiting runs in order. |
| `GET /admin/training/api/runs` | Run history (`?limit=`, default 50, at most 500). |
| `GET /admin/training/api/runs/<run_id>` | One run's record, plus `review`: precision from review verdicts on its predictions. |
| `GET /admin/training/api/runs/<run_id>/events` | The run's event log (`?limit=`, default 200). |
| `POST /admin/training/api/runs` | Start a run: `200` when it starts, `202` with `queued: true` and `position` when it waits behind the run in progress. |
| `GET /admin/training/api/backends` | The configured backends. |
| `POST /admin/training/api/backends/<name>/check` | For an ssh backend, connect and report Python, GPUs and missing packages. For a slurm backend, connect to the login node and check for `sbatch`, `squeue` and `scancel` and a shared `remote_dir`. For an agent backend, whether a token is issued and when the agent last connected. |
| `POST /admin/training/api/runs/<run_id>/cancel` | Cancel the run in progress, or a waiting run. `400` if `<run_id>` is neither. |
| `DELETE /admin/training/api/runs/<run_id>/predictions` | Withdraw the run's stored predictions. |
| `POST /admin/training/api/runs/<run_id>/push-to-hub` | Push the run's model to the Hugging Face Hub. Body: `repo_id`, `confirm_repo_id` (the same), `private` (default `true`), `token_env` (default `HF_TOKEN`), `licence`, `accept_licence`. `201` with the commit; `400` for a mismatch, a missing token variable, no model files or an unconfirmed licence; `409` for a public repository when `private` is set; `502` when the Hub refuses. |
| `POST /admin/training/api/runs/<run_id>/pin-split` | Save a split as a dataset version. Body: `{"dataset": name, "split": "val"}`. `201` with the version; `400` with no dataset name, a split the run lacks, or datasets not enabled; `404` for an unknown run. |
| `GET /admin/training/api/pinned` | Pinned items, by reason. |
| `POST /admin/training/api/pinned` | Pin items to `train`: `{"slice": name}` or `{"instance_ids": [...]}`. Returns how many were new, already pinned, or not in the data, and `in_last_run_train`: how many the latest run already trained on. Train items get no prelabel, so `model-found-nothing` matches them too. |
| `DELETE /admin/training/api/pinned` | Unpin `{"instance_ids": [...]}`, or every pinned item when `instance_ids` is left out. `400` when `instance_ids` is not a non-empty list of ids. |

Starting a run:

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/admin/training/api/runs \
  -d '{"trainer": "sklearn-text", "schemas": ["species"],
       "params": {"vectorizer": "clip",
                  "vectorizer_kwargs": {"model_name": "clip-ViT-B-32"}}}'
```

The body takes `trainer`, `schemas` (a list, or one name as a string),
`params`, `backend` (default `model_training.backend`), `accept_licence`, and
`queue` (default `true`; see [The run queue](#the-run-queue)). A refused
start gives the reason in `error`:

| Status | When |
|---|---|
| `400` | No trainer or no scheme in the body; an unknown trainer or scheme; a scheme the trainer cannot learn; a trainer this project cannot run (such as `decision-calibrate` with no decision model); a trainer whose licence needs acknowledging, with `needs_licence_ack: true`, until the request sets `accept_licence: true` |
| `409` | A parameter the trainer does not take, or of the wrong type or range; an unknown backend; `decision-calibrate` on a backend other than `local`; a run already in progress, with `"queue": false` |
| `429` | `queue_max` runs are already waiting |

The Runs table's score column is the run's [held-out score](#held-out-scores).
The `review` figures on `/api/runs/<run_id>` are measured on predictions a
human looked at.

### Agent protocol

`model_training.enabled` also registers the routes an agent uses, under
`/api/training`. An agent sends its token as `Authorization: Bearer <token>`;
registering takes the admin API key instead. Agents call these routes, and
`potato/training/protocol.py` describes them for anyone writing their own
agent.

| Route | Purpose |
|---|---|
| `POST /api/training/backends/register` | Issue an agent token for a backend name (`X-API-Key` required). `potato training register` calls it. |
| `POST /api/training/backends/<name>/heartbeat` | An idle agent says it is alive. `403` for a token issued to another backend. |
| `GET /api/training/jobs/next?wait=30` | Long poll: `200` with a job, or `204` when none arrives within `wait` seconds. |
| `GET /api/training/jobs/<run_id>` | The job, its spec and whether it was cancelled. |
| `GET /api/training/jobs/<run_id>/bundle` | The bundle as `tar.gz`, media included. Answers `Range` requests: the agent resumes a dropped download from where it stopped, up to five attempts. `410` once the bundle is gone. |
| `POST /api/training/jobs/<run_id>/progress` | Progress events; a cancel comes back in the response. |
| `POST /api/training/jobs/<run_id>/predictions` | `predictions.jsonl`. `413` above `max_predictions_mb`. |
| `POST /api/training/jobs/<run_id>/complete` | Exit code and final events. |

A missing or invalid token is `401`. These routes, and the admin page's
JSON routes under `/admin/training/api/`, are in the
[OpenAPI spec](../api-reference/openapi.json), marked
`x-potato-requires-config: model_training.enabled: true`.

---

### QLoRA: 4-bit base weights

`llm-sft`, `llm-dpo`, `hf-text-classification` and `vlm-sft` take
`lora: {quantize: 4bit}`. The base model is loaded with its weights in 4 bits
(NF4 with double quantization, the QLoRA setup), and a LoRA adapter is trained
on top of it in bf16 where the GPU supports bf16. In 4 bits the base weights
take a quarter of the memory they take in bf16; activations, the adapter and
its optimizer state come on top. A QLoRA run's memory has not been measured
on a GPU yet, so check the run's "Peak GPU memory" line rather than plan
from the arithmetic. `quantize: 8bit` is the halfway option. Predictions load the base model the
same way.

```yaml
model_training:
  trainer_params:
    llm-sft:
      model_name: Qwen/Qwen2.5-7B-Instruct
      lora: {quantize: 4bit}
```

It needs a CUDA GPU and a `bitsandbytes` build for that machine's CUDA. The
run checks both before it loads anything, by quantizing a few numbers on the
GPU. Without them the run stops at validation, and when the two versions do
not match the error names both. Every transformer run logs its "Peak GPU
memory" at the end, which shows what quantization saved.

## Where runs are stored

Each run has a directory under
`<task_dir>/<output_annotation_dir>/training/runs/<run_id>/`:

| Path | Contents |
|---|---|
| `bundle/` | The training data: `train.jsonl`, `val.jsonl`, `test.jsonl`, `unlabeled.jsonl` (with `include_unlabeled`), `labels.json`, `manifest.json`, and `media/` (symlinks to the images, or copies where symlinks are unavailable). |
| `artifacts/` | `model_card.json` and `predictions.jsonl`, and the model: `model.pkl` for `sklearn-text`; a `model/` directory for the transformer trainers, holding the weights (or only the LoRA adapter) and the tokenizer or image processor; `model/` and `head.pkl` for `setfit`. |
| `spec.json` | What the run was asked to do. |
| `events.jsonl`, `stdout.log`, `stderr.log` | The run's progress events and output. On a remote backend the events arrive over the protocol, and the worker's output stays on the remote host in `remote_dir/jobs/<run_id>/`. |
| `agent.log` | ssh backends: the remote agent's own output. |
| `bundle.tar.gz` | Remote backends: the bundle as the agent downloaded it, media included. |

The ledger (runs, each item's split per run, stored predictions, agent
tokens, and pushes to the Hub) is in the project database,
`<task_dir>/project.sqlite`, in the tables `training_runs`,
`training_run_items`, `training_predictions`, `training_backends` and
`training_hub_pushes`.

Set `POTATO_MODEL_CACHE` to a directory to have the training process use it
for `HF_HOME`, `TRANSFORMERS_CACHE` and `SENTENCE_TRANSFORMERS_HOME`, unless
those are already set. On an air-gapped machine, put the models the trainers
name there in advance.

A run with LoRA saves only the adapter, a few to a few hundred megabytes, and
loads the base model by its `model_name` when it predicts. A full fine-tune
saves the whole model. On an ssh backend that model is copied back to the
server, and over a slow link a 330 MB model takes minutes; the run's step line
shows how much has arrived. `fetch_artifacts: false` leaves models on the
remote host.

### Publish a model to the Hugging Face Hub

A successful run whose model is on this server has **Publish to the Hugging
Face Hub** on its run page. It uploads the model and a `README.md` model card
written from the run: the trainer, base model and adapter, the schemes and
labels, the split sizes, the held-out score and what it was measured on, and
the run and bundle ids.

What is uploaded is a fixed list, not everything in `artifacts/`:

- weights (`.safetensors`, `.bin`, `.pt`, `.pth`, `.pkl`, `.joblib`, `.onnx`,
  `.gguf`);
- the configs and tokenizer files in the saved `model/` directory;
- `model_card.json`, with local paths replaced by file names, and
  `calibration.json`.

`artifacts/` also holds the model's answers on this project's items
(`predictions.jsonl`, and `raw_answers.jsonl` for the decision models), some
trainers' copies of the training data (`yolo_data/`, `wev_data/`,
`laya_data/`), checkpoints and optimizer state. None of these goes up, and
neither does a symlink that points outside `artifacts/`.

- The repository name is typed twice, and the push goes ahead only when the
  two match.
- **Private** is ticked by default. While it is, an existing repository that
  is public is not pushed to; untick it to publish there.
- The form names an environment variable on the server (`HF_TOKEN` by
  default) that holds a Hugging Face write token. The token itself is not
  typed into the page. The variable's name must contain `TOKEN` or start with
  `HF_`, and its value must start with `hf_`, so no other variable's value is
  sent to the Hub.
- When the Hub cannot say whether the repository exists (an error other than
  "not found", or no connection), nothing is pushed. A repository the push
  created is deleted again if the upload then fails.
- The model card's licence is the Hub licence id you give, such as
  `apache-2.0`. With none, the card says the base model's licence applies. A
  trainer whose licence needs confirming before use, such as
  `ultralytics-detect` (AGPL-3.0), needs the same confirmation to push, since
  its weights carry that licence.
- A model left on a remote host (`fetch_artifacts: false`) cannot be pushed
  from here, and the page says where it is.

Each push is one commit. The run page lists every push with its repository,
visibility and commit, and the ledger records who made it.

---

## Troubleshooting

**`/admin/training` returns 404.** `model_training.enabled` is not `true`. The
routes are registered only when it is.

**"Only N items in the train split; this trainer needs at least 10."**
Annotate more items, or lower `min_instances` in `params`. The train split is
70% of the labelled items by default.

**"Schema 'x' has 1 distinct label(s) in the data."** A classifier needs at
least two labels in use.

**"No resolved annotations to train on."** The scheme named in the run does
not match the scheme being annotated, or nothing has been annotated.

**The run was killed and the message says the machine ran out of memory.** The
process exited on SIGKILL, usually the out-of-memory killer. Use a smaller
model, fewer items, or set `max_ram_mb` so the run fails inside its own limit.

**An ssh run fails with "ssh to host failed: Permission denied".** Potato runs
`ssh` with `BatchMode=yes`, so it needs a key that works without a prompt:
`ssh host true` from the server's account must succeed. A key with a
passphrase works when `ssh-agent` holds it.

**"No GPU has N MB free".** Every GPU on the host is busier than
`min_free_gpu_mb` allows. `potato training check <backend> config.yaml` lists
them. Wait, lower the threshold, or pin a GPU with `gpus: "1"`.

**An ssh run fails with "Trainer ... could not be imported".** The remote
interpreter lacks a package the trainer needs. Point `python` at an
interpreter that has it, or list it under `packages`.

**"No word from the agent on X for 120 seconds".** The agent stopped
reporting: the remote machine or the network went away. On an ssh backend,
`agent.log` in the run directory has the agent's last output.

**A run on an agent backend stays queued.** No agent with that backend name is
polling. Start one with `potato training agent --backend <name>`, and check the
token with **Check** on the Training page.

**The run published no prelabels.** Read the `writeback` report in
`/admin/training/api/status`: its `summary` says what happened, and "No
predictions were published: write-back is not enabled for any schema" means
`writeback.schemas` is empty. The skip counts say how many predictions each
check removed.

**"Stopped: the run took longer than model_training.max_wall_seconds", or on
an ssh or agent backend "The run exceeded model_training.max_wall_seconds".**
The run reached the time limit and was stopped. Raise `max_wall_seconds`, or
train on less.

**"SLURM job N ended before the worker finished: it reached its time
limit".** The job ran out of its `time`. Raise `time` in the backend, or
train on less. "Its node failed" and "it was cancelled" come from SLURM's own
`slurm.out` in the job directory; set `keep_remote: true` to keep it for
reading.

**An image run trained on file names.** No item field named the image (see
[Image items](#image-items)), so the bundle was not marked as
an image corpus, or the run's `params` named a text vectorizer.

**"<trainer> does not take <name>".** A parameter in the run, or under
`trainer_params`, is misspelt or belongs to another trainer. The message lists
the names the trainer takes.

**"This host's torch has no kernels for any of its GPUs", or a GPU listed
with "torch there has no kernels for it".** The remote interpreter's torch was
built for newer GPUs than the host has (a TITAN V, compute 7.0, with a torch
built for 7.5 and up). `gpus: auto` skips such GPUs; pinning one is refused.
Install a torch build for them, or use another GPU.

**A transformer run fails with "The GPU ran out of memory".** Lower
`batch_size` and raise `gradient_accumulation` to keep the effective batch,
set `lora: true` or `lora: {quantize: 4bit}`, or for `llm-sft` set
`gradient_checkpointing: true` or choose a smaller model.

**"... has no fast tokenizer, and span training needs one".** Choose another
model for `hf-token-classification`; most encoder models on the Hugging Face
hub have one.

**An ssh run's copy back fails with "sent nothing for 180 s".** The network to
the host stopped while the model was being copied. The run's predictions are
already stored; only the model files are missing from `artifacts/`.

**"ultralytics-detect is licensed AGPL-3.0"** (or `ultralytics-segment`). The
run was started without confirming the licence; see
[`ultralytics-detect`](#ultralytics-detect).

**A detection run's held-out score is 0.** A box counts only when it overlaps an
annotated box of the same label by IoU 0.5. Check that the run trained on more
than a few images (the run log gives images and boxes), that `score_threshold`
is not dropping every box, and that `pretrained` is on.

**A run on a GPU host fails with "nvrtc: error: failed to open
libnvrtc-builtins.so.13.0".** The host's torch was built for one CUDA version
and its `nvidia-cuda-nvrtc` package is for another, so torch cannot compile
the kernels it builds at run time. Any CUDA program that needs those kernels
fails there, not only Potato: `torch.rand(3, 3, device="cuda").prod(1)` is a
quick test. Install the `nvidia-cuda-nvrtc` that matches the torch build, or
point `python` at another interpreter. YOLO-seg's loss needs those kernels;
the detection trainers ran on the same host without them.

**An audio run left out its recordings.** The run log says "Left out N ...
row(s) with no local audio file": the audio is at remote URLs, or the files are
not where the item points.

**An image run left out most of its rows.** The run log says "Left out N ...
row(s) with no local image file": the images are remote URLs or the files are
not where the reference points. Store them under `media_directory` (or give
paths relative to `task_dir`).

---

## Related documentation

- [Reviewing Model Output](model_review.md): the review queue that prelabels feed
- [Agent protocol](#agent-protocol): `potato/training/agent.py` is the reference implementation of an agent
- [Active Learning Guide](active_learning_guide.md) and
  [Vision Active Learning](vision_active_learning.md): ordering items by model uncertainty
- [Labeling engine distillation](../labeling-engine/configuration.md#distill):
  a trained model as the first tier of the engine's cascade
