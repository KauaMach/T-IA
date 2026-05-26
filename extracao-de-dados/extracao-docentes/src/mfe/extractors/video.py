"""
Video content extractor.

Pipeline:
1. Extract audio from video using ffmpeg
2. Transcribe audio via Groq Whisper API (chunked if > 24 MB)
3. Extract frames at scene changes via ffmpeg
4. OCR frames using the existing DeepSeek OCR extractor
5. Return structured text combining transcript + frame OCR
"""

import asyncio
import os
import subprocess
import sys  # noqa: E402
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv  # noqa: E402

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
load_dotenv(os.path.join(root_dir, ".env"))

from src.mfe.config.logging import create_logger

logger, error_logger = create_logger("video_extractor")

# Groq's file size limit for audio uploads
_GROQ_MAX_BYTES = 24 * 1024 * 1024  # 24 MB (leaving margin from 25 MB limit)
_AUDIO_SEGMENT_SECONDS = 600  # 10-minute chunks


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------


def _run_ffmpeg(*args: str) -> None:
    """Run an ffmpeg command, raising on failure and suppressing console output."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *args]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}):\n"
            f"{result.stderr.decode(errors='replace')}"
        )


def _extract_audio(video_path: str, output_audio_path: str) -> None:
    """Extract mono 16 kHz MP3 audio track from a video file."""
    _run_ffmpeg(
        "-i",
        video_path,
        "-vn",  # no video stream
        "-ac",
        "1",  # mono
        "-ar",
        "16000",  # 16 kHz — optimal for Whisper
        "-q:a",
        "4",  # VBR quality level (small file)
        output_audio_path,
        "-y",
    )


def _split_audio(audio_path: str, output_dir: str) -> List[str]:
    """Split an audio file into ≤10-minute segments. Returns sorted list of chunk paths."""
    pattern = os.path.join(output_dir, "chunk_%04d.mp3")
    _run_ffmpeg(
        "-i",
        audio_path,
        "-f",
        "segment",
        "-segment_time",
        str(_AUDIO_SEGMENT_SECONDS),
        "-c",
        "copy",
        pattern,
        "-y",
    )
    return sorted(str(p) for p in Path(output_dir).glob("chunk_*.mp3"))


def _transcribe_file(audio_path: str, groq_client) -> str:
    """Transcribe a single audio file with Groq Whisper. Returns plain text."""
    with open(audio_path, "rb") as f:
        response = groq_client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=f,
            response_format="text",
            language="pt",  # hint Portuguese; Whisper auto-detects if wrong
        )
    # response is a plain string when response_format="text"
    return response if isinstance(response, str) else str(response)


def transcribe_audio(video_path: str, groq_api_key: str) -> str:
    """
    Full audio transcription pipeline:
    - Extracts audio from video
    - Splits into chunks if > 24 MB
    - Transcribes each chunk with Groq Whisper
    - Returns combined transcript text
    """
    from groq import Groq

    client = Groq(api_key=groq_api_key)

    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = os.path.join(tmp_dir, "audio.mp3")
        logger.info(f"[Video] Extraindo áudio de: {os.path.basename(video_path)}")
        _extract_audio(video_path, audio_path)

        file_size = os.path.getsize(audio_path)
        logger.info(f"[Video] Áudio extraído: {file_size / 1024 / 1024:.1f} MB")

        if file_size <= _GROQ_MAX_BYTES:
            chunks = [audio_path]
        else:
            logger.info("[Video] Arquivo grande — dividindo em segmentos de 10 min")
            chunks_dir = os.path.join(tmp_dir, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            chunks = _split_audio(audio_path, chunks_dir)
            logger.info(f"[Video] {len(chunks)} segmentos criados")

        parts = []
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"[Video] Transcrevendo segmento {i}/{len(chunks)}")
            text = _transcribe_file(chunk, client)
            parts.append(text.strip())

        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Frame extraction helpers
# ---------------------------------------------------------------------------


def extract_scene_frames(
    video_path: str,
    output_dir: str,
    scene_threshold: float = 0.35,
    max_frames: int = 50,
) -> List[str]:
    """
    Extract frames at scene changes using ffmpeg's scene detection filter.

    scene_threshold: 0.0-1.0 sensitivity (higher = fewer frames)
    max_frames: safety cap to avoid thousands of frames in long videos
    Returns sorted list of saved PNG file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_pattern = os.path.join(output_dir, "frame_%04d.png")

    # scale=960:-1 downscales width to 960px preserving aspect ratio — good enough for OCR
    vf_filter = f"select='gt(scene,{scene_threshold})',scale=960:-1"

    _run_ffmpeg(
        "-i",
        video_path,
        "-vf",
        vf_filter,
        "-vsync",
        "vfr",
        "-frames:v",
        str(max_frames),
        output_pattern,
        "-y",
    )

    return sorted(str(p) for p in Path(output_dir).glob("frame_*.png"))


# ---------------------------------------------------------------------------
# Audio-only extractor
# ---------------------------------------------------------------------------


async def extract_audio_content(audio_path: str, groq_api_key: str) -> str:
    """
    Extract text content from an audio file via Groq Whisper transcription.
    No frame extraction — audio only.
    """
    filename = os.path.basename(audio_path)
    sections: List[str] = [f"# Transcrição de Áudio: {filename}\n"]

    try:
        from groq import Groq

        client = Groq(api_key=groq_api_key)

        file_size = os.path.getsize(audio_path)
        logger.info(
            f"[Audio] Transcrevendo: {filename} ({file_size / 1024 / 1024:.1f} MB)"
        )

        if file_size <= _GROQ_MAX_BYTES:
            transcript = await asyncio.to_thread(_transcribe_file, audio_path, client)
        else:
            logger.info("[Audio] Arquivo grande — dividindo em segmentos de 10 min")
            with tempfile.TemporaryDirectory() as tmp_dir:
                chunks = await asyncio.to_thread(_split_audio, audio_path, tmp_dir)
                logger.info(f"[Audio] {len(chunks)} segmentos criados")
                parts = []
                for i, chunk in enumerate(chunks, 1):
                    logger.info(f"[Audio] Transcrevendo segmento {i}/{len(chunks)}")
                    text = await asyncio.to_thread(_transcribe_file, chunk, client)
                    parts.append(text.strip())
                transcript = "\n\n".join(parts)

        sections.append(
            transcript.strip() if transcript.strip() else "_Nenhuma fala detectada._"
        )

    except Exception as e:
        error_logger.error(f"[Audio] Falha na transcrição: {e}")
        sections.append(f"_Erro na transcrição: {e}_")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


async def extract_video_content(
    video_path: str,
    groq_api_key: str,
    local_base_directory: Optional[str] = None,
    frames_output_dir: Optional[str] = None,
    use_frame_ocr: bool = True,
) -> str:
    """
    Extract structured text content from a video file.

    Returns a markdown-formatted string combining:
    - Audio transcript (via Groq Whisper)
    - OCR of scene-change frames (via DeepSeek OCR, if available)

    Args:
        frames_output_dir: persistent directory to save extracted frames.
                           If None, frames are saved to a temporary directory and deleted after.
    """
    sections: List[str] = []
    filename = os.path.basename(video_path)
    video_stem = Path(video_path).stem

    sections.append(f"# Conteúdo do Vídeo: {filename}\n")

    # ------------------------------------------------------------------
    # 1. Audio transcription
    # ------------------------------------------------------------------
    try:
        transcript = await asyncio.to_thread(transcribe_audio, video_path, groq_api_key)
        if transcript.strip():
            sections.append("## Transcrição de Áudio\n")
            sections.append(transcript.strip())
        else:
            sections.append("## Transcrição de Áudio\n")
            sections.append("_Nenhuma fala detectada no vídeo._")
    except Exception as e:
        error_logger.error(f"[Video] Falha na transcrição de áudio: {e}")
        sections.append("## Transcrição de Áudio\n")
        sections.append(f"_Erro na transcrição: {e}_")

    # ------------------------------------------------------------------
    # 2. Scene frame extraction + OCR
    # ------------------------------------------------------------------
    if use_frame_ocr:
        # Use persistent dir (frames/<video_stem>/) or a temp dir that is cleaned up
        if frames_output_dir is not None:
            named_frames_dir = os.path.join(frames_output_dir, video_stem)
            os.makedirs(named_frames_dir, exist_ok=True)
            ctx = None
        else:
            _tmp = tempfile.TemporaryDirectory()
            named_frames_dir = _tmp.name
            ctx = _tmp

        try:
            logger.info(f"[Video] Extraindo frames por mudança de cena: {filename}")
            frame_paths = await asyncio.to_thread(
                extract_scene_frames, video_path, named_frames_dir
            )
            logger.info(
                f"[Video] {len(frame_paths)} frames extraídos em: {named_frames_dir}"
            )

            if frame_paths:
                from src.mfe.extractors.deepseek_ocr import (
                    extract_text_from_image_bytes,
                )

                frame_sections: List[Tuple[int, str]] = []

                for i, frame_path in enumerate(frame_paths, 1):
                    logger.info(
                        f"[Video] OCR frame {i}/{len(frame_paths)}: {os.path.basename(frame_path)}"
                    )
                    try:
                        with open(frame_path, "rb") as f:
                            image_bytes = f.read()

                        ocr_text = await extract_text_from_image_bytes(
                            image_bytes=image_bytes,
                            max_tokens=1024,
                            page_num=i,
                            local_base_directory=local_base_directory
                            or named_frames_dir,
                            upload_s3_enabled=False,
                        )

                        if ocr_text and ocr_text.strip():
                            frame_sections.append((i, ocr_text.strip()))

                    except Exception as e:
                        error_logger.warning(f"[Video] OCR falhou no frame {i}: {e}")

                if frame_sections:
                    sections.append("\n## Conteúdo Visual (Frames de Cena)\n")
                    for frame_num, text in frame_sections:
                        sections.append(f"### Frame {frame_num}\n")
                        sections.append(text)

        except Exception as e:
            error_logger.error(f"[Video] Falha na extração de frames: {e}")
        finally:
            if ctx is not None:
                ctx.cleanup()

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Validação manual — execute diretamente: python src/mfe/extractors/video.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys  # noqa: E402

    from dotenv import load_dotenv  # noqa: E402

    root_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    load_dotenv(os.path.join(root_dir, ".env"))

    VIDEO_PATH = os.path.join(
        root_dir,
        "data",
        "input",
        "raw",
        "files_to_rename",
        "files_to_rename",
        "2022",
        "06",
        "28",
        "Apresentaa&#769;&#8710;o - ArvoreBinariaUI.mkv",
    )
    OUTPUT_PATH = os.path.join(
        root_dir, "data", "output", "video_test", "video_test_output.txt"
    )
    FRAMES_DIR = os.path.join(root_dir, "data", "output", "video_test", "frames")

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        print("GROQ_API_KEY não encontrada no .env")
        sys.exit(1)

    async def _run():
        print(f"Processando: {VIDEO_PATH}")
        content = await extract_video_content(
            video_path=VIDEO_PATH,
            groq_api_key=groq_key,
            frames_output_dir=FRAMES_DIR,
            use_frame_ocr=True,  # mude para True se o servidor DeepSeek estiver rodando
        )
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Saída salva em: {OUTPUT_PATH}")
        print(f"Tokens aproximados: {len(content.split())}")

    asyncio.run(_run())
