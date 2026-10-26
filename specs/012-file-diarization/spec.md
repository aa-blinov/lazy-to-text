# Feature Specification: Speaker diarization for files

**Status**: Implemented

**Changes baseline specs**: 002-model-management (a card that is not a speech model), 003-file-transcription (a per-file option and a labelled result).

## User Scenarios & Testing

### User Story 1 - Split a file by speaker (Priority: P1)

A user with a recording of several people ticks "Split by speakers (diarization)" on the Transcribe screen before adding the file. The transcript comes back as paragraphs, `Speaker 1: ...`, `Speaker 2: ...`, in the interface language ("Спикер 1" in Russian). It is edited, copied and saved exactly like a plain transcript, because it is plain text.

**Acceptance Scenarios**:

1. **Given** the model is downloaded and the box is ticked, **When** a file with two voices is added, **Then** the transcript has one labelled paragraph per speaker turn, numbered from 1 in order of first appearance.
2. **Given** the box is ticked, **When** the file holds one voice (or no speech found), **Then** the ordinary transcript is returned, with no labels.
3. **Given** the box is clear, **Then** the run is the one spec 003 describes, and the diarizer is not touched.

### User Story 2 - The model is a download like any other (Priority: P1)

The diarization model (pyannote segmentation + CAM++ voice embedder, about 34 MB, ONNX, CPU only) is the last card on the Models page. It is downloaded and deleted there, lives in the same hub cache (so Storage, moving the folder and the Hugging Face token apply), and is never the active speech model: no Select, no WER.

**Acceptance Scenarios**:

1. **Given** it is not downloaded, **Then** its card is dimmed, Download is the only action, and the Transcribe box is greyed out and disabled with the tooltip "Download the diarization model in Models to split a file by speakers."
2. **Given** a download runs, **Then** the card shows bytes and a bar; speech-model switches and a second download are refused as `busy`, and it is refused while a speech model loads.
3. **Given** it is downloaded, **Then** the card offers Delete, the box is enabled, and deleting it clears a tick that was set.
4. A run asked to diarize without the model fails before it starts with `diarization_missing`.

## Requirements

- **FR-001**: `files.transcribe` accepts `diarize` (bool) and `speaker_label` (string, 1-40 chars). Without `diarize` the backend call is the unchanged `transcribe_file(path)`.
- **FR-002**: Diarization runs in the inference worker, next to the speech model: segmentation finds speaker turns, embeddings are clustered, each turn is transcribed on its own by the loaded model (so it works for every model, with no word timestamps).
- **FR-003**: `models.list` appends the card `{kind: "diarization", alias: "diarization"}`; `cached["diarization"]` and `diarization_downloading` ride on the model state. Events: `diarization_progress`, `diarization_download`. `models.download`, `models.delete` and `models.delete_info` accept the alias; `models.select` does not.
- **FR-004**: The diarization model alone on disk does not count as "a speech model is on disk".
- **FR-005**: The runtime stays free of UI toolkits and adds no dependency: `onnx-asr`, `onnxruntime` and `huggingface_hub` are already shipped; no PyTorch.

## Where it lives

`app/diarization.py` (algorithm, from the protokol project), `app/diarization_models.py` (disk, download), `app/model_mapping.py:DIARIZATION`, `app/backends/onnx_backend.py:_transcribe_by_speaker`, `app/server/handlers/{files,models}.py`, `desktop/renderer/src/{views/Transcribe.svelte,lib/transcribe.js,components/models}`. Tests: `tests/test_diarization.py`, `tests/backends/test_diarized_file.py`, `tests/server/test_{models,files}.py`, `desktop/tests/{models,transcribe}.test.js`.

## Assumptions

- Clustering thresholds are protokol's, picked there on VoxConverse and AMI; not re-measured on Russian dictation here. The embedder is trained on Chinese and English speech.
- A diarized run is not re-run when the box is ticked after a file is loaded; the box applies to the next file.
