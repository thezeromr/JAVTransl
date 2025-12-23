import argparse
import os
from pathlib import Path
import sys

from faster_whisper import WhisperModel

_BASE_DIR = Path(__file__).resolve().parent
_CUDNN_DIR = _BASE_DIR / "lib" / "cudnn"
_CUDA_DIR = _BASE_DIR / "lib" / "cuda"
if _CUDNN_DIR.is_dir():
    os.add_dll_directory(str(_CUDNN_DIR))
if _CUDA_DIR.is_dir():
    os.add_dll_directory(str(_CUDA_DIR))


def _create_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _transcribe_to_srt(
    model: WhisperModel,
    input_path: str,
    output_path: str,
    language: str,
    beam_size: int,
    vad_filter: bool,
    vad_threshold: float,
) -> None:
    kwargs = {
        "task": "transcribe",
        "language": language,
        "beam_size": beam_size,
        "without_timestamps": False,
        "log_progress": True,
    }
    if vad_filter:
        kwargs["vad_filter"] = True
        kwargs["vad_parameters"] = {"threshold": vad_threshold}

    segments, _info = model.transcribe(input_path, **kwargs)

    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n{seg.start:.2f} --> {seg.end:.2f}\n{seg.text}\n\n")



def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch transcribe files with faster-whisper.")
    parser.add_argument("inputs", nargs="+", help="Input audio/video paths.")
    parser.add_argument("--model", default="large-v3", help="Whisper model name.")
    parser.add_argument("--language", default="ja", help="Language code.")
    parser.add_argument("--device", default="cuda", help="Device for inference.")
    parser.add_argument("--compute-type", default="float16", help="Compute type.")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam size.")
    parser.add_argument("--vad-threshold", type=float, default=0.6, help="VAD threshold.")
    parser.add_argument("--no-vad", action="store_true", help="Disable VAD.")
    return parser


def main(argv: list[str]) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    model = _create_model(args.model, device=args.device, compute_type=args.compute_type)
    failed = False

    for input_path in args.inputs:
        print(f"starting to process: {input_path}", flush=True)
        if not os.path.exists(input_path):
            print(f"missing file: {input_path}", flush=True)
            failed = True
            continue

        output_path = str(Path(input_path).with_suffix(".srt"))
        try:
            _transcribe_to_srt(
                model=model,
                input_path=input_path,
                output_path=output_path,
                language=args.language,
                beam_size=args.beam_size,
                vad_filter=not args.no_vad,
                vad_threshold=args.vad_threshold,
            )
        except Exception as exc:
            print(f"failed to transcribe {input_path}: {exc}", flush=True)
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
