#!/usr/bin/env python3
import base64
import cgi
import hashlib
import json
import mimetypes
import os
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OCR_SCRIPT = ROOT / "scripts" / "vision_ocr.swift"
PDF_RENDER_SCRIPT = ROOT / "scripts" / "render_pdf_pages.swift"
MODEL_CONFIG_PATH = ROOT / "model_config.json"
ENV_PATH = ROOT / ".env"
TEXT_EXTS = {".txt", ".md", ".csv", ".json"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
OCR_EXTS = IMAGE_EXTS | {".pdf"}
ALLOWED_EXTS = TEXT_EXTS | OCR_EXTS | {".zip"}
ACCESS_COOKIE_NAME = "ai_grading_access"
DEFAULT_ACCESS_PASSWORD = ""
EXTRACT_JOBS = {}
EXTRACT_JOBS_LOCK = threading.Lock()


def load_dotenv():
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_model_config():
    config = {
        "enabled": True,
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "api_key": "",
        "local_model": {
            "enabled": True,
            "provider": "ollama",
            "api_url": "http://127.0.0.1:11434/api/chat",
            "model": "qwen2.5vl:7b",
            "vision_enabled": True,
            "vision_model": "qwen2.5vl:7b",
        },
    }
    if MODEL_CONFIG_PATH.exists():
        try:
            file_config = json.loads(MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                config.update(file_config)
        except json.JSONDecodeError:
            print("Warning: model_config.json 格式错误，已使用默认模型配置。")
    return config


load_dotenv()
MODEL_CONFIG = load_model_config()


def get_access_password():
    return os.environ.get("ACCESS_PASSWORD", DEFAULT_ACCESS_PASSWORD).strip()


def is_access_control_enabled():
    return bool(get_access_password())


def build_access_token():
    seed = f"{get_access_password()}::{ROOT}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def parse_cookie_header(header):
    cookies = {}
    for item in str(header or "").split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        cookies[key.strip()] = urllib.parse.unquote(value.strip())
    return cookies


def https_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def parse_ocr_questions(text):
    questions = []
    seen = set()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    answer_markers = ("答案", "参考答案", "Answer", "answer", "ans")

    for line in lines:
        compact = re.sub(r"\s+", " ", line)
        if compact.startswith("==="):
            continue
        rubric_match = re.match(
            r"^(?:第\s*)?([0-9一二三四五六七八九十]+)\s*(?:题)?[\.\．\、\):：\s-]*(.+?)(?:评分点|采分点|关键词|rubric|keywords)[：:\s-]*(.+)$",
            compact,
            re.IGNORECASE,
        )
        if rubric_match:
            no = normalize_no(rubric_match.group(1))
            qid = f"q{no}"
            if qid not in seen:
                title = rubric_match.group(2).strip(" ：:-")
                points = [
                    item.strip()
                    for item in re.split(r"[、,，;；|/]", rubric_match.group(3))
                    if item.strip()
                ]
                seen.add(qid)
                questions.append(
                    {
                        "id": qid,
                        "subject": "",
                        "type": "essay" if "作文" in title else "history",
                        "title": title or f"第 {no} 题",
                        "answer": "",
                        "score": infer_score_from_text(compact),
                        "keywords": points,
                        "rubric": points,
                        "source": "ocr",
                    }
                )
            continue

        # Common forms:
        # 1. B
        # 1、答案：B
        # 第1题 答案 B
        match = re.match(
            r"^(?:第\s*)?([0-9一二三四五六七八九十]+)\s*(?:题)?[\.\．\、\):：\s-]*(?:答案|参考答案|ans|answer)?[\s:：-]*([A-Da-d对错√×真假]|-?\d+(?:\.\d+)?|[\u4e00-\u9fa5]{1,12})$",
            compact,
            re.IGNORECASE,
        )
        if match:
            no = normalize_no(match.group(1))
            qid = f"q{no}"
            if qid not in seen:
                seen.add(qid)
                answer = match.group(2).strip()
                questions.append(
                    {
                        "id": qid,
                        "subject": "",
                        "type": "choice" if re.fullmatch(r"[A-Da-d]", answer) else "fill",
                        "title": f"第 {no} 题",
                        "answer": answer.upper() if re.fullmatch(r"[A-Da-d]", answer) else answer,
                        "score": infer_score_from_text(compact),
                        "keywords": [],
                        "rubric": [],
                        "source": "ocr",
                    }
                )
            continue

        if any(marker in compact for marker in answer_markers):
            pair_matches = re.findall(
                r"([0-9]{1,2})\s*[\.\．\、\):：-]?\s*([A-Da-d对错√×]|-?\d+(?:\.\d+)?)",
                compact,
            )
            for no, answer in pair_matches:
                no = normalize_no(no)
                qid = f"q{no}"
                if qid in seen:
                    continue
                seen.add(qid)
                questions.append(
                    {
                        "id": qid,
                        "subject": "",
                        "type": "choice" if re.fullmatch(r"[A-Da-d]", answer) else "fill",
                        "title": f"第 {no} 题",
                        "answer": answer.upper() if re.fullmatch(r"[A-Da-d]", answer) else answer,
                        "score": infer_score_from_text(compact),
                        "keywords": [],
                        "rubric": [],
                        "source": "ocr",
                    }
                )

    return questions


def normalize_no(value):
    value = str(value).strip()
    if value.isdigit():
        return str(int(value))
    return value


def run_vision_ocr(path):
    completed = subprocess.run(
        ["swift", str(OCR_SCRIPT), "--json", str(path)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "OCR 失败")
    try:
        payload = json.loads(completed.stdout)
        return payload.get("text", ""), "macos-vision", {
            "average_confidence": payload.get("average_confidence", 0),
            "line_count": payload.get("line_count", 0),
            "low_confidence_count": payload.get("low_confidence_count", 0),
            "lines": payload.get("lines", []),
        }
    except json.JSONDecodeError:
        return completed.stdout.strip(), "macos-vision", {}


def extract_plain_or_ocr(path, ext):
    if ext in TEXT_EXTS:
        return Path(path).read_text(encoding="utf-8", errors="ignore"), "text", {}
    if ext in OCR_EXTS:
        return run_vision_ocr(path)
    raise ValueError(f"暂不支持 {ext or '未知'} 文件")


def get_vision_max_images(target=None):
    env_name = ""
    if target == "reference":
        env_name = "VISION_MAX_IMAGES_REFERENCE"
    elif target == "submission":
        env_name = "VISION_MAX_IMAGES_SUBMISSION"
    try:
        value = os.environ.get(env_name) if env_name else None
        return max(1, int(value or os.environ.get("VISION_MAX_IMAGES", "6")))
    except ValueError:
        return 6


def get_vision_total_image_limit(target=None, ext=""):
    env_name = ""
    if target == "reference":
        env_name = "VISION_MAX_TOTAL_IMAGES_REFERENCE"
    elif target == "submission":
        env_name = "VISION_MAX_TOTAL_IMAGES_SUBMISSION"
    fallback = get_vision_max_images(target)
    default_value = 24 if target == "reference" and ext == ".zip" else fallback
    try:
        value = os.environ.get(env_name) if env_name else None
        return max(1, int(value or os.environ.get("VISION_MAX_TOTAL_IMAGES", default_value)))
    except ValueError:
        return default_value


def get_vision_batch_size(target=None):
    env_name = ""
    if target == "reference":
        env_name = "VISION_BATCH_SIZE_REFERENCE"
    elif target == "submission":
        env_name = "VISION_BATCH_SIZE_SUBMISSION"
    try:
        value = os.environ.get(env_name) if env_name else None
        return max(1, int(value or os.environ.get("VISION_BATCH_SIZE", "8")))
    except ValueError:
        return 8


def get_vision_batch_max_bytes(target=None):
    env_name = ""
    if target == "reference":
        env_name = "VISION_BATCH_MAX_MB_REFERENCE"
    elif target == "submission":
        env_name = "VISION_BATCH_MAX_MB_SUBMISSION"
    try:
        value = os.environ.get(env_name) if env_name else None
        mb = float(value or os.environ.get("VISION_BATCH_MAX_MB", "18"))
        return max(2 * 1024 * 1024, int(mb * 1024 * 1024))
    except ValueError:
        return 18 * 1024 * 1024


def get_vision_image_max_dim():
    try:
        return max(900, int(os.environ.get("VISION_IMAGE_MAX_DIM", "1600")))
    except ValueError:
        return 1600


def get_pdf_render_scale():
    try:
        value = float(os.environ.get("PDF_RENDER_SCALE", "3.0"))
        return min(4.0, max(1.5, value))
    except ValueError:
        return 3.0


def is_vision_configured():
    settings = get_vision_settings()
    return bool(settings["enabled"] and settings["api_key"])


def should_use_vision_first(ext, target):
    if ext not in OCR_EXTS:
        return False
    value = os.environ.get("VISION_FIRST", "true").strip().lower()
    if value in ("0", "false", "no"):
        return False
    return is_vision_configured()


def render_pdf_images(path, out_dir, max_images=None):
    completed = subprocess.run(
        [
            "swift",
            str(PDF_RENDER_SCRIPT),
            str(path),
            str(out_dir),
            str(max_images or get_vision_max_images()),
            str(get_pdf_render_scale()),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "PDF 渲染图片失败")
    try:
        return [item for item in json.loads(completed.stdout) if item]
    except json.JSONDecodeError:
        return []


def decode_zip_member_name(name):
    try:
        repaired = str(name).encode("cp437").decode("utf-8")
        if repaired:
            return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return str(name)


def zip_member_priority(member):
    decoded_name = decode_zip_member_name(member.filename)
    name = Path(decoded_name).name
    lower_name = name.lower()
    is_answer_version = any(keyword in name for keyword in ("答案版", "解析版", "参考答案", "评分版", "标准答案"))
    is_paper_version = any(keyword in name for keyword in ("原卷", "试卷版", "试题版", "题目版"))
    is_answer = is_answer_version or any(keyword in name for keyword in ("答案", "参考答案", "评分", "标准答案")) or any(
        keyword in lower_name for keyword in ("answer", "key", "rubric", "solution")
    )
    is_paper = is_paper_version or any(keyword in name for keyword in ("试卷", "试题", "题目")) or any(
        keyword in lower_name for keyword in ("paper", "exam", "question")
    )
    if is_answer and not is_paper_version:
        bucket = 0
    elif is_paper:
        bucket = 1
    else:
        bucket = 2
    return bucket, decoded_name


def extract_zip(path, vision_dir=None, max_images=None):
    texts = []
    files = []
    sections = []
    vision_images = []
    confidence_values = []
    low_confidence_count = 0
    line_count = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(path) as archive:
            members = [
                item
                for item in archive.infolist()
                if not item.is_dir()
                and not item.filename.startswith("__MACOSX/")
                and not Path(item.filename).name.startswith(".")
            ]
            members.sort(key=zip_member_priority)

            for index, member in enumerate(members, start=1):
                decoded_filename = decode_zip_member_name(member.filename)
                name = Path(decoded_filename).name
                ext = Path(name).suffix.lower()
                if ext not in (TEXT_EXTS | OCR_EXTS):
                    continue
                extracted = Path(tmpdir) / f"{index:03d}{ext}"
                extracted.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(extracted, "wb") as dst:
                    dst.write(src.read())
                try:
                    text, engine, ocr = extract_plain_or_ocr(extracted, ext)
                except RuntimeError as error:
                    if ext not in OCR_EXTS:
                        raise
                    text, engine, ocr = "", "ocr-failed", {"error": str(error)}
                vision_limit = max_images or get_vision_max_images()
                if vision_dir and len(vision_images) < vision_limit:
                    if ext in IMAGE_EXTS:
                        vision_copy = Path(vision_dir) / f"{len(vision_images) + 1:03d}_{Path(member.filename).stem}{ext}"
                        vision_copy.write_bytes(Path(extracted).read_bytes())
                        vision_images.append(str(vision_copy))
                    elif ext == ".pdf":
                        pdf_out = Path(vision_dir) / f"{len(vision_images) + 1:03d}_{Path(member.filename).stem}"
                        rendered = render_pdf_images(extracted, pdf_out, vision_limit)
                        remaining = vision_limit - len(vision_images)
                        vision_images.extend(rendered[:remaining])
                avg_conf = ocr.get("average_confidence")
                if isinstance(avg_conf, (int, float)) and avg_conf > 0:
                    confidence_values.append(avg_conf)
                low_confidence_count += int(ocr.get("low_confidence_count", 0) or 0)
                line_count += int(ocr.get("line_count", 0) or 0)
                files.append({"name": decoded_filename, "engine": engine, "chars": len(text), "ocr": summarize_ocr(ocr)})
                if text.strip():
                    sections.append({"name": decoded_filename, "engine": engine, "text": text.strip(), "ocr": summarize_ocr(ocr)})
                    texts.append(f"=== {decoded_filename} ===\n{text.strip()}")

    ocr_summary = {
        "average_confidence": sum(confidence_values) / len(confidence_values) if confidence_values else 0,
        "line_count": line_count,
        "low_confidence_count": low_confidence_count,
    }
    return "\n\n".join(texts), files, sections, ocr_summary, vision_images


def summarize_ocr(ocr):
    if not ocr:
        return {}
    summary = {
        "average_confidence": ocr.get("average_confidence", 0),
        "line_count": ocr.get("line_count", 0),
        "low_confidence_count": ocr.get("low_confidence_count", 0),
    }
    if ocr.get("error"):
        summary["error"] = ocr.get("error")
    return summary


def questions_to_readable_text(questions):
    lines = []
    for question in questions or []:
        qid = question.get("id", "")
        title = question.get("title", "")
        answer = question.get("answer", "")
        score = question.get("score", 0)
        rubric = question.get("rubric") or []
        lines.append(f"{qid} {title}".strip())
        if score:
            lines.append(f"分值：{score}")
        if answer:
            lines.append(f"参考答案：{answer}")
        if rubric:
            lines.append("评分点：" + "；".join(str(item) for item in rubric))
        lines.append("")
    return "\n".join(lines).strip()


def students_to_readable_text(students):
    lines = []
    for student in students or []:
        lines.append(str(student.get("student") or "未知学生"))
        answers = student.get("answers") or {}
        for qid in sorted(answers, key=sort_question_id):
            lines.append(f"{qid}：{answers[qid]}")
        lines.append("")
    return "\n".join(lines).strip()


def sort_question_id(qid):
    parts = re.findall(r"\d+", str(qid))
    return tuple(int(part) for part in parts) if parts else (9999,)


def is_question_extraction_too_weak(questions, text=""):
    if not questions:
        return True
    compact = re.sub(r"\s+", "", str(text or ""))
    expected_numbers = [int(item) for item in re.findall(r"(?:第)?([0-9]{1,2})(?:题|[\.．、])", compact)]
    expected_max = max(expected_numbers) if expected_numbers else 0
    if expected_max >= 10 and len(questions) < max(6, expected_max // 2):
        return True
    if len(questions) <= 2 and any(keyword in compact for keyword in ("答案", "解析", "本小题", "选择题", "填空题", "解答题")):
        return True
    return False


def needs_reference_text_completion(questions, text=""):
    if not questions or not str(text or "").strip():
        return False
    compact = re.sub(r"\s+", "", str(text or ""))
    if not any(keyword in compact for keyword in ("答案", "解析", "评分", "采分点", "参考")):
        return False
    if len(questions) < 8:
        return False
    answered = 0
    rubriced = 0
    for question in questions:
        if str(question.get("answer") or "").strip():
            answered += 1
        if question.get("rubric") or question.get("评分点"):
            rubriced += 1
    return answered < max(5, int(len(questions) * 0.72)) and rubriced < max(3, int(len(questions) * 0.45))


def complete_questions_from_text_if_needed(questions, text):
    if not (is_question_extraction_too_weak(questions, text) or needs_reference_text_completion(questions, text)):
        return questions, None
    text_questions, text_message, text_source = llm_extract_questions_chunked(text)
    if not text_questions:
        return questions, {"message": text_message, "source": text_source}
    merged = merge_question_lists([questions, text_questions])
    if question_quality({"answer": questions_to_readable_text(merged)}) >= question_quality({"answer": questions_to_readable_text(questions)}):
        return merged, {"message": text_message, "source": text_source}
    return questions, {"message": text_message, "source": text_source}


def structure_questions_from_text(text):
    questions = parse_ocr_questions(text)
    llm_questions, llm_message, llm_source = llm_extract_questions_chunked(text)
    if llm_questions:
        questions = normalize_llm_questions(llm_questions, llm_source)
    return questions, {
        "enabled": is_llm_configured(),
        "model": os.environ.get("LLM_MODEL") or MODEL_CONFIG.get("model", ""),
        "source": llm_source,
        "cloud_timeout": get_cloud_timeout(),
        "local_model": get_local_model_public_settings(),
        "message": llm_message,
    }


def structure_students_from_text(text):
    students = []
    llm_students, llm_message, llm_source = llm_extract_students(text)
    if llm_students:
        students = normalize_model_students(llm_students)
    return students, {
        "enabled": is_llm_configured(),
        "model": os.environ.get("LLM_MODEL") or MODEL_CONFIG.get("model", ""),
        "source": llm_source,
        "cloud_timeout": get_cloud_timeout(),
        "local_model": get_local_model_public_settings(),
        "message": llm_message,
    }


def structure_questions_from_images(image_paths, ocr_text="", max_images=None, progress_callback=None):
    questions = parse_ocr_questions(ocr_text)
    vision_questions, vision_message = cloud_vision_extract_questions(image_paths, ocr_text, max_images, progress_callback=progress_callback)
    if vision_questions:
        completed_questions, completion_meta = complete_questions_from_text_if_needed(vision_questions, ocr_text)
        if completion_meta and completed_questions:
            vision_questions = completed_questions
            vision_message = f"{vision_message}；已使用 OCR 文本分块补全。{completion_meta.get('message', '')}"
        return normalize_llm_questions(vision_questions, "vision"), {
            "enabled": is_llm_configured(),
            "model": get_vision_settings()["model"],
            "source": "vision",
            "cloud_timeout": get_cloud_timeout(),
            "local_model": get_local_model_public_settings(),
            "message": vision_message,
        }

    local_vision_questions, local_vision_message = local_vision_extract_questions(image_paths, ocr_text, max_images, progress_callback=progress_callback)
    if local_vision_questions:
        completed_questions, completion_meta = complete_questions_from_text_if_needed(local_vision_questions, ocr_text)
        if completion_meta and completed_questions:
            local_vision_questions = completed_questions
            local_vision_message = f"{local_vision_message}；已使用 OCR 文本分块补全。{completion_meta.get('message', '')}"
        return normalize_llm_questions(local_vision_questions, "local_vision"), {
            "enabled": is_llm_configured(),
            "model": get_local_model_settings()["vision_model"],
            "source": "local_vision",
            "cloud_timeout": get_cloud_timeout(),
            "local_model": get_local_model_public_settings(),
            "message": f"{vision_message}；{local_vision_message}",
        }

    if not str(ocr_text or "").strip():
        return questions, {
            "enabled": is_llm_configured(),
            "model": get_vision_settings()["model"],
            "source": "vision_failed_no_ocr",
            "cloud_timeout": get_cloud_timeout(),
            "local_model": get_local_model_public_settings(),
            "message": f"{vision_message}；{local_vision_message}；未获得 OCR 文本，已触发 OCR 回退，不使用空文本让大模型猜题。",
        }

    llm_questions, llm_message, llm_source = llm_extract_questions_chunked(ocr_text)
    if llm_questions:
        questions = normalize_llm_questions(llm_questions, llm_source)
    return questions, {
        "enabled": is_llm_configured(),
        "model": get_vision_settings()["model"],
        "source": llm_source,
        "cloud_timeout": get_cloud_timeout(),
        "local_model": get_local_model_public_settings(),
        "message": f"{vision_message}；{local_vision_message}；{llm_message}",
    }


def structure_students_from_images(image_paths, ocr_text="", allow_vision=True, max_images=None):
    if allow_vision and image_paths:
        students, message = cloud_vision_extract_students(image_paths, ocr_text, max_images)
        if students:
            return normalize_model_students(students), {
                "enabled": is_llm_configured(),
                "model": get_vision_settings()["model"],
                "source": "student_vision",
                "cloud_timeout": get_cloud_timeout(),
                "local_model": get_local_model_public_settings(),
                "message": message,
            }
        local_students, local_message = local_vision_extract_students(image_paths, ocr_text, max_images)
        if local_students:
            return normalize_model_students(local_students), {
                "enabled": is_llm_configured(),
                "model": get_local_model_settings()["vision_model"],
                "source": "student_local_vision",
                "cloud_timeout": get_cloud_timeout(),
                "local_model": get_local_model_public_settings(),
                "message": f"{message}；{local_message}",
            }
        fallback_message = f"{message}；{local_message}"
    elif not image_paths:
        fallback_message = "未检测到可传给视觉模型的图片页，已使用 OCR/文本分段解析。"
    else:
        fallback_message = "学生作业文件较多，已跳过视觉模型，使用 OCR 分段解析，避免大批量超时。"
    return [], {
        "enabled": is_llm_configured(),
        "model": get_vision_settings()["model"],
        "source": "student_ocr",
        "cloud_timeout": get_cloud_timeout(),
        "local_model": get_local_model_public_settings(),
        "message": fallback_message,
    }


def build_question_extract_prompt(text):
    return (
        "你是试卷答案结构化助手。请从 OCR 文本中识别题目编号、题型、题干、答案和评分点。"
        "必须遵守："
        "1. 先识别大题分区，例如选择题、填空题、解答题、作文、阅读理解、证明题。"
        "2. 如果题面写了选择题共10题，则 1-10 题都应标为 choice，不要把第7题误判成填空题。"
        "3. 如果 OCR 把题号和答案拆散，要按题号递增、分区标题和上下文修正。"
        "4. 参考答案可能是老师手写的，OCR 可能出现断行、错别字、字母数字混淆；要结合题号、题型和上下文谨慎还原。"
        "5. 数学符号尽量规范：导数用 f′(x) 或 dy/dx，积分用 ∫，极限用 lim，偏导用 ∂，趋于用 →，无穷用 ∞；保留 ln、sin、cos、tan、e^x、x^x、分段函数、参数方程和隐函数方程。"
        "6. 不要凭空补标准答案、评分点、关键词、分值或题干；无法可靠识别的字段必须留空或用 []，不要猜。"
        "7. 主观题要保留题干 title/stem；只有图片/OCR 中明确出现参考答案、评分点、采分点、关键词时，才写入 answer/rubric/keywords。"
        "8. 如果题干明确出现“本小题满分10分”“满分10分”“（10分）”，score 写 10；如果没有明确分值，score 写 0。"
        "9. 计算题、证明题、材料题、作文等主观题只有在参考答案/解析中明确出现“6分/4分/评分点/采分点”等评分信息时，才写入 rubric；否则 rubric 返回 []。"
        "10. 只返回 JSON 数组，每项包含 id、type、title、stem、answer、score、keywords、rubric。"
        "11. id 使用 q1、q2 格式；type 使用 choice/fill/calculation/proof/geometry/calculus/derivative/integral/limit/essay/history/politics/subjective。"
        "OCR 文本如下：\n" + text[:12000]
    )


def build_student_extract_prompt(text):
    return (
        "你是学生作业 OCR 文本结构化助手。请从 OCR 文本中提取学生姓名、题号和学生作答。"
        "必须遵守："
        "1. 目标是提取学生答案，不是提取参考答案。不要把印刷题干、选项、说明文字当成学生作答。"
        "2. 如果文本来自同一名学生的整张试卷，无法识别姓名时 student 使用“未知学生”。"
        "3. 选择题优先识别学生在括号、选项旁、题号旁写下或圈选的 A/B/C/D。"
        "4. 填空题、计算题、证明题要保留学生写下的表达式、步骤和结论。"
        "5. 数学符号尽量规范：因为用 ∵，所以用 ∴，角用 ∠1/∠ABC，三角形用 △ABC，垂直用 ⊥，平行用 ∥；导数用 f′(x) 或 dy/dx，积分用 ∫，极限用 lim，偏导用 ∂，趋于用 →，无穷用 ∞。"
        "6. 题号统一为 q1、q2、q22_1；只提取能对应到题号的作答。"
        "7. 只返回 JSON 数组，每项格式为 {student: 学生姓名或未知学生, answers: {q1: 作答, q22_1: 作答}}。"
        "OCR 文本如下：\n" + text[:12000]
    )


def build_student_vision_prompt(ocr_text):
    return (
        "你是学生答卷视觉解析助手。请直接观察图片，不要只依赖 OCR。"
        "目标不是生成参考答案，而是提取学生姓名、题号和学生作答内容。"
        "适用于答题卡、数学计算题、几何证明题、物理图题、化学装置/方程式题。"
        "数学符号必须尽量规范：因为用 ∵，所以用 ∴，角用 ∠ABC，三角形用 △ABC，垂直用 ⊥，平行用 ∥；导数用 f′(x) 或 dy/dx，积分用 ∫，极限用 lim，偏导用 ∂，趋于用 →，无穷用 ∞。"
        "遇到微积分题要保留 ln、sin、cos、tan、e^x、x^x、lim_{x→0}、分段函数、参数方程和隐函数方程，不要改写成口语描述。"
        "如果看到图形作答、辅助线、证明步骤、公式推导，请完整保留在对应题号答案中。"
        "只返回 JSON 数组，每项格式为 {student: 学生姓名或文件中可见标识, answers: {q1: 作答, q22_1: 作答}}。"
        "如果无法识别学生姓名，student 使用“未知学生”。"
        "题号统一为 q1、q2、q22_1。不要输出解释。"
        "以下 OCR 文本仅作辅助，若与图片冲突，以图片为准：\n"
        + (ocr_text or "")[:6000]
    )


def build_submission_bundle_vision_prompt(ocr_text, need_questions=False):
    question_part = (
        "同时只解析同一套试卷中能够看清的题目结构，输出 questions。"
        "questions 每项包含 id、type、title、stem、answer、score、keywords、rubric、visual_notes。"
        "如果题目、分值、答案、评分点看不清或没有出现，对应字段留空、0 或 []，不要猜。"
        if need_questions
        else "不需要输出 questions。"
    )
    return (
        "你是学生答卷视觉解析助手。请直接观察图片，不要只依赖 OCR。"
        "请一次性完成学生作答解析，避免重复读图。"
        "输出必须是 JSON 对象，格式为 {\"students\": [...], \"questions\": [...]}。"
        "students 每项格式为 {student: 学生姓名或文件中可见标识, answers: {q1: 作答, q22_1: 作答}}。"
        "目标是提取学生真实写下、圈选或填涂的答案，不要把印刷题干、选项、说明文字当成学生答案。"
        "数学符号尽量规范：因为用 ∵，所以用 ∴，角用 ∠ABC，三角形用 △ABC，垂直用 ⊥，平行用 ∥；导数用 f′(x) 或 dy/dx，积分用 ∫，极限用 lim，偏导用 ∂，趋于用 →，无穷用 ∞。"
        "遇到微积分题要保留 ln、sin、cos、tan、e^x、x^x、lim_{x→0}、分段函数、参数方程和隐函数方程，不要改写成口语描述。"
        "如果看到几何图、辅助线、公式推导、证明步骤，请保留在对应题号答案中。"
        "无法识别学生姓名时 student 使用“未知学生”。题号统一为 q1、q2、q22_1。"
        + question_part
        + "只返回 JSON，不要输出解释。"
        "以下 OCR 文本仅作辅助，若与图片冲突，以图片为准：\n"
        + (ocr_text or "")[:6000]
    )


def build_vision_extract_prompt(ocr_text):
    return (
        "你是数学、物理、化学试卷的视觉结构化助手。请直接观察图片，不要只依赖 OCR。"
        "如果收到多张图片，请把它们视为同一份试卷/答案的连续页面，按页序合并分析。"
        "重点识别题干、公式、几何图形、函数图像、物理电路/受力图、化学结构/装置图，以及老师手写的参考答案或评分点。"
        "数学符号必须尽量规范：因为用 ∵，所以用 ∴，角用 ∠ABC，三角形用 △ABC，垂直用 ⊥，平行用 ∥；导数用 f′(x) 或 dy/dx，积分用 ∫，极限用 lim，偏导用 ∂，趋于用 →，无穷用 ∞。"
        "遇到微积分题要保留 ln、sin、cos、tan、e^x、x^x、lim_{x→0}、分段函数、参数方程和隐函数方程，不要改写成口语描述。"
        "如果题目包含图形，请在 title 或 stem 中描述图形关系，例如点、线段、角、平行/垂直/相交/中点/辅助线/图号。"
        "如果图片中有参考答案、证明步骤或评分点，请写入 answer/rubric/keywords。"
        "如果题干明确出现“本小题满分10分”“满分10分”“（10分）”，score 写 10；如果没有明确分值，score 写 0。"
        "计算题、证明题、材料题、作文等主观题只有在图片或 OCR 中明确出现“6分/4分/评分点/采分点”等评分信息时，才写入 rubric；否则 rubric 返回 []。"
        "不要凭空补标准答案、评分点、关键词、分值或题干；看不清或无法确认的字段留空或 []。"
        "只返回 JSON 数组，每项包含 id、type、title、stem、answer、score、keywords、rubric、visual_notes。"
        "id 使用 q1、q2、q22_1 这种格式；type 可用 choice/fill/calculation/proof/geometry/calculus/derivative/integral/limit/physics/chemistry/subjective。"
        "以下 OCR 文本仅作辅助，若与图片冲突，以图片为准：\n"
        + (ocr_text or "")[:6000]
    )


def image_to_data_url(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = Path(path).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_to_base64(path):
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def optimize_vision_image(path):
    max_dim = get_vision_image_max_dim()
    source = Path(path)
    if not source.exists():
        return str(path)
    try:
        if source.stat().st_size < 700 * 1024:
            return str(path)
    except OSError:
        return str(path)
    output = source.with_name(f"{source.stem}-vision.jpg")
    if output.exists():
        return str(output)
    completed = subprocess.run(
        ["sips", "-s", "format", "jpeg", "-Z", str(max_dim), str(source), "--out", str(output)],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode == 0 and output.exists():
        try:
            return str(output) if output.stat().st_size < source.stat().st_size else str(path)
        except OSError:
            return str(output)
    return str(path)


def prepare_vision_images(image_paths):
    return [optimize_vision_image(path) for path in image_paths or []]


def chunk_list(items, size):
    size = max(1, int(size or 1))
    for index in range(0, len(items), size):
        yield items[index:index + size]


def estimate_image_payload_bytes(path):
    try:
        return int(Path(path).stat().st_size * 1.38) + 2000
    except OSError:
        return 0


def chunk_vision_images(image_paths, target=None):
    max_count = get_vision_batch_size(target)
    max_bytes = get_vision_batch_max_bytes(target)
    batches = []
    current = []
    current_bytes = 0
    for image_path in image_paths or []:
        image_bytes = estimate_image_payload_bytes(image_path)
        if current and (len(current) >= max_count or current_bytes + image_bytes > max_bytes):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(image_path)
        current_bytes += image_bytes
    if current:
        batches.append(current)
    return batches


def question_quality(question):
    if not isinstance(question, dict):
        return 0
    score = 0
    for key, weight in (("answer", 4), ("答案", 4), ("rubric", 3), ("评分点", 3), ("keywords", 2), ("关键词", 2), ("title", 1), ("题目", 1), ("stem", 1), ("题干", 1)):
        value = question.get(key)
        if isinstance(value, list) and value:
            score += weight + len(value)
        elif str(value or "").strip():
            score += weight + min(6, len(str(value)) // 80)
    if question.get("score") or question.get("分值"):
        score += 1
    return score


def merge_question_items(base, incoming):
    merged = dict(base or {})
    for key, value in (incoming or {}).items():
        if value in (None, "", [], {}):
            continue
        current = merged.get(key)
        if current in (None, "", [], {}, 0):
            merged[key] = value
            continue
        if key in ("answer", "答案", "rubric", "评分点", "keywords", "关键词"):
            if len(str(value)) > len(str(current)):
                merged[key] = value
    if question_quality(incoming) > question_quality(base) + 4:
        for key, value in (incoming or {}).items():
            if value not in (None, "", [], {}):
                merged[key] = value
    return merged


def normalize_math_answer_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\\text\s*\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\mathrm\s*\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\left\s*", "", text)
    text = re.sub(r"\\right\s*", "", text)
    text = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"√\1", text)
    text = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", text)
    text = text.replace("\\[", "[").replace("\\]", "]")
    text = text.replace("\\(", "(").replace("\\)", ")")
    text = text.replace("\\,", "").replace("\\;", "")
    text = text.replace("\\cdot", "·").replace("\\times", "×")
    text = text.replace("\\leq", "≤").replace("\\geq", "≥").replace("\\neq", "≠")
    text = text.replace("\\infty", "∞").replace("\\to", "→")
    text = re.sub(r"\(\s*([0-9a-zA-Z√²³]+)\s*\)\s*/\s*\(\s*([0-9a-zA-Z√²³]+)\s*\)", r"\1/\2", text)
    text = re.sub(r"\((e\^2-1)\)/\((e\^2\+1)\)", r"(e²-1)/(e²+1)", text)
    text = re.sub(r"e\^2", "e²", text)
    text = re.sub(r"√\s*\(?\s*([0-9a-zA-Z]+)\s*\)?\s*/\s*\(?\s*([0-9a-zA-Z]+)\s*\)?", r"√\1/\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_answer_parts(answer):
    text = str(answer or "").strip()
    if not text:
        return {}
    parts = {}
    pattern = re.compile(r"(?:^|[;；。]\s*)[（(]\s*([0-9一二三四五六七八九十]+)\s*[）)]\s*")
    matches = list(pattern.finditer(text))
    for index, match in enumerate(matches):
        key = normalize_no(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip(" ;；。")
        if value:
            parts[str(key)] = value
    return parts


def sync_parent_answers_from_subquestions(questions):
    by_id = {}
    for question in questions or []:
        if isinstance(question, dict):
            by_id[str(question.get("id") or "")] = question
    for qid, parent in list(by_id.items()):
        if "_" in qid:
            continue
        children = []
        prefix = f"{qid}_"
        for child_id, child in by_id.items():
            if child_id.startswith(prefix):
                suffix = child_id[len(prefix):]
                children.append((sort_question_id(child_id), suffix, child))
        if not children:
            parent["answer"] = normalize_math_answer_text(parent.get("answer") or "")
            continue
        children.sort(key=lambda item: item[0])
        parent_parts = split_answer_parts(parent.get("answer") or "")
        merged_parts = {}
        for _, suffix, child in children:
            child_answer = normalize_math_answer_text(child.get("answer") or "")
            child["answer"] = child_answer
            parent_answer = normalize_math_answer_text(parent_parts.get(suffix, ""))
            merged_parts[suffix] = child_answer or parent_answer
        if merged_parts:
            parent["answer"] = "；".join(f"({suffix}) {answer}" for suffix, answer in merged_parts.items() if answer)
    return questions


def merge_question_lists(question_lists):
    merged = {}
    order = []
    for questions in question_lists:
        for item in questions or []:
            if not isinstance(item, dict):
                continue
            raw_id = str(item.get("id") or item.get("question_id") or item.get("题号") or "").strip()
            if raw_id:
                no = normalize_no(re.sub(r"^q", "", raw_id, flags=re.I))
                qid = f"q{no}"
            else:
                qid = f"q{len(order) + 1}"
            if qid not in merged:
                order.append(qid)
                merged[qid] = item
            else:
                merged[qid] = merge_question_items(merged[qid], item)
    return sync_parent_answers_from_subquestions([merged[qid] for qid in sorted(order, key=sort_question_id)])


def parse_model_questions_content(content):
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
    if not (content.startswith("[") or content.startswith("{")):
        array_match = re.search(r"\[[\s\S]*\]", content)
        object_match = re.search(r"\{[\s\S]*\}", content)
        if array_match:
            content = array_match.group(0)
        elif object_match:
            content = object_match.group(0)
    try:
        items = json.loads(content)
    except json.JSONDecodeError:
        # Math answers often contain backslashes such as \frac or \sqrt that are
        # valid math notation but invalid JSON escapes. Preserve them as text.
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", content)
        items = json.loads(repaired)
    if isinstance(items, dict):
        items = items.get("questions") or items.get("students") or items.get("items") or []
    return items if isinstance(items, list) else []


def parse_model_json_content(content):
    content = str(content or "").strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
    if not (content.startswith("[") or content.startswith("{")):
        object_match = re.search(r"\{[\s\S]*\}", content)
        array_match = re.search(r"\[[\s\S]*\]", content)
        if object_match:
            content = object_match.group(0)
        elif array_match:
            content = array_match.group(0)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", content)
        return json.loads(repaired)


def cloud_llm_extract_questions(text):
    if not MODEL_CONFIG.get("enabled", True):
        return [], "云端大模型解析未启用。"
    api_key_env = MODEL_CONFIG.get("api_key_env") or "OPENAI_API_KEY"
    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get(api_key_env)
        or MODEL_CONFIG.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
    )
    api_url = os.environ.get("LLM_API_URL") or MODEL_CONFIG.get("api_url", "https://api.openai.com/v1/chat/completions")
    model = os.environ.get("LLM_MODEL") or MODEL_CONFIG.get("model", "gpt-4o-mini")
    if not api_key:
        return [], f"未配置 {api_key_env}/LLM_API_KEY。"

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": build_question_extract_prompt(text)},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=get_cloud_timeout(), context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"].strip()
        return parse_model_questions_content(content), f"云端大模型结构化解析完成（{model}）。"
    except Exception as error:
        return [], f"云端大模型解析失败：{format_url_error(error)}"


def cloud_llm_extract_students(text):
    if not MODEL_CONFIG.get("enabled", True):
        return [], "云端大模型解析未启用。"
    api_key_env = MODEL_CONFIG.get("api_key_env") or "OPENAI_API_KEY"
    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get(api_key_env)
        or MODEL_CONFIG.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
    )
    api_url = os.environ.get("LLM_API_URL") or MODEL_CONFIG.get("api_url", "https://api.openai.com/v1/chat/completions")
    model = os.environ.get("LLM_MODEL") or MODEL_CONFIG.get("model", "gpt-4o-mini")
    if not api_key:
        return [], f"未配置 {api_key_env}/LLM_API_KEY。"

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": build_student_extract_prompt(text)},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=get_cloud_timeout(), context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"].strip()
        return parse_model_questions_content(content), f"云端大模型学生作答结构化完成（{model}）。"
    except Exception as error:
        return [], f"云端大模型学生作答解析失败：{format_url_error(error)}"


def get_vision_settings():
    settings = get_llm_settings()
    return {
        "enabled": str(os.environ.get("VISION_LLM_ENABLED", "true")).lower() not in ("0", "false", "no"),
        "api_key": os.environ.get("VISION_LLM_API_KEY") or settings["api_key"],
        "api_url": os.environ.get("VISION_LLM_API_URL") or settings["api_url"],
        "model": os.environ.get("VISION_LLM_MODEL") or settings["model"],
    }


def cloud_vision_extract_questions(image_paths, ocr_text="", max_images=None, progress_callback=None):
    settings = get_vision_settings()
    if not settings["enabled"]:
        return [], "视觉模型解析未启用。"
    if not settings["api_key"]:
        return [], "未配置视觉模型 API key。"

    limit = max_images or get_vision_max_images()
    image_paths = prepare_vision_images((image_paths or [])[:limit])
    batches = chunk_vision_images(image_paths, "reference")
    if len(batches) > 1:
        all_questions = []
        messages = []
        total_batches = len(batches)
        for batch_index, batch in enumerate(batches, start=1):
            if progress_callback:
                progress_callback(
                    35 + int((batch_index - 1) / max(1, total_batches) * 35),
                    "vision_question_batch",
                    f"正在调用视觉模型解析第 {batch_index}/{total_batches} 批页面（每批最多 {get_vision_batch_size('reference')} 张）。",
                )
            batch_questions, batch_message = cloud_vision_extract_questions(batch, ocr_text, len(batch), progress_callback=None)
            if batch_questions:
                all_questions.append(batch_questions)
            messages.append(f"第{batch_index}批：{batch_message}")
        merged = merge_question_lists(all_questions)
        if merged:
            return merged, f"视觉模型分批看图解析完成（{settings['model']}，{len(image_paths)} 张图，批量上限 {get_vision_batch_size('reference')}）。" + "；".join(messages)
        return [], "；".join(messages)

    content = [{"type": "text", "text": build_vision_extract_prompt(ocr_text)}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})

    body = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=get_cloud_timeout(), context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"].strip()
        return parse_model_questions_content(content), f"视觉模型直接看图解析完成（{settings['model']}，{len(image_paths)} 张图）。"
    except Exception as error:
        if len(image_paths) > 1:
            midpoint = max(1, len(image_paths) // 2)
            left_questions, left_message = cloud_vision_extract_questions(image_paths[:midpoint], ocr_text, len(image_paths[:midpoint]), progress_callback=None)
            right_questions, right_message = cloud_vision_extract_questions(image_paths[midpoint:], ocr_text, len(image_paths[midpoint:]), progress_callback=None)
            merged = merge_question_lists([left_questions, right_questions])
            if merged:
                return merged, f"视觉模型 {len(image_paths)} 张批量请求失败，已自动拆分重试：{format_url_error(error)}；{left_message}；{right_message}"
        return [], f"视觉模型直接看图解析失败：{format_url_error(error)}"


def cloud_vision_extract_students(image_paths, ocr_text="", max_images=None):
    settings = get_vision_settings()
    if not settings["enabled"]:
        return [], "学生答案视觉解析未启用。"
    if not settings["api_key"]:
        return [], "未配置视觉模型 API key。"

    content = [{"type": "text", "text": build_student_vision_prompt(ocr_text)}]
    limit = max_images or get_vision_max_images()
    image_paths = prepare_vision_images((image_paths or [])[:limit])
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})

    body = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=get_cloud_timeout(), context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"].strip()
        items = parse_model_questions_content(content)
        return items, f"学生答案视觉解析完成（{settings['model']}，{len(image_paths)} 张图）。"
    except Exception as error:
        return [], f"学生答案视觉解析失败：{format_url_error(error)}"


def cloud_vision_extract_submission_bundle(image_paths, ocr_text="", need_questions=False, max_images=None):
    settings = get_vision_settings()
    if not settings["enabled"]:
        return [], [], "学生答案视觉解析未启用。"
    if not settings["api_key"]:
        return [], [], "未配置视觉模型 API key。"

    content = [{"type": "text", "text": build_submission_bundle_vision_prompt(ocr_text, need_questions)}]
    limit = max_images or get_vision_max_images("submission")
    image_paths = prepare_vision_images((image_paths or [])[:limit])
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})

    body = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=get_cloud_timeout(), context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"].strip()
        parsed = parse_model_json_content(content)
        if isinstance(parsed, list):
            return parsed, [], f"学生答案视觉解析完成（{settings['model']}，{len(image_paths)} 张图）。"
        students = parsed.get("students") or parsed.get("学生") or []
        questions = parsed.get("questions") or parsed.get("题目") or []
        message = f"学生答案与题目视觉合并解析完成（{settings['model']}，{len(image_paths)} 张图）。"
        return students, questions, message
    except Exception as error:
        return [], [], f"学生答案与题目视觉合并解析失败：{format_url_error(error)}"


def get_local_model_settings():
    local_config = MODEL_CONFIG.get("local_model") or {}
    enabled = str(os.environ.get("LOCAL_LLM_ENABLED", local_config.get("enabled", True))).lower() not in ("0", "false", "no")
    vision_enabled = str(os.environ.get("LOCAL_VISION_ENABLED", local_config.get("vision_enabled", enabled))).lower() not in ("0", "false", "no")
    default_model = local_config.get("model", "qwen2.5vl:7b")
    return {
        "enabled": enabled,
        "provider": os.environ.get("LOCAL_LLM_PROVIDER") or local_config.get("provider", "ollama"),
        "api_url": os.environ.get("LOCAL_LLM_API_URL") or local_config.get("api_url", "http://127.0.0.1:11434/api/chat"),
        "model": os.environ.get("LOCAL_LLM_MODEL") or default_model,
        "vision_enabled": vision_enabled,
        "vision_model": os.environ.get("LOCAL_VISION_MODEL") or local_config.get("vision_model") or default_model,
        "timeout": int(os.environ.get("LOCAL_LLM_TIMEOUT", "180")),
    }


def local_vision_chat(prompt, image_paths, max_images=None):
    settings = get_local_model_settings()
    if not settings["enabled"]:
        return "", "本地模型解析未启用。"
    if not settings["vision_enabled"]:
        return "", "本地视觉模型解析未启用。"
    if settings["provider"] != "ollama":
        return "", f"暂只支持 Ollama 本地视觉模型，当前 provider={settings['provider']}。"

    limit = max_images or get_vision_max_images()
    image_paths = prepare_vision_images((image_paths or [])[:limit])
    images = []
    for image_path in image_paths:
        try:
            images.append(image_to_base64(image_path))
        except Exception:
            continue
    if not images:
        return "", "没有可传给本地视觉模型的图片。"

    body = {
        "model": settings["vision_model"],
        "stream": False,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": prompt, "images": images},
        ],
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = (payload.get("message") or {}).get("content", "").strip()
        return content, f"本地视觉模型看图解析完成（{settings['provider']} / {settings['vision_model']}，{len(images)} 张图）。"
    except Exception as error:
        return "", f"本地视觉模型看图解析失败：{format_url_error(error)}"


def local_vision_extract_questions(image_paths, ocr_text="", max_images=None, progress_callback=None):
    limit = max_images or get_vision_max_images()
    image_paths = prepare_vision_images((image_paths or [])[:limit])
    batches = chunk_vision_images(image_paths, "reference")
    if len(batches) > 1:
        all_questions = []
        messages = []
        total_batches = len(batches)
        for batch_index, batch in enumerate(batches, start=1):
            if progress_callback:
                progress_callback(
                    55 + int((batch_index - 1) / max(1, total_batches) * 25),
                    "local_vision_question_batch",
                    f"正在用本地视觉模型解析第 {batch_index}/{total_batches} 批页面（每批最多 {get_vision_batch_size('reference')} 张）。",
                )
            batch_questions, batch_message = local_vision_extract_questions(batch, ocr_text, len(batch), progress_callback=None)
            if batch_questions:
                all_questions.append(batch_questions)
            messages.append(f"第{batch_index}批：{batch_message}")
        merged = merge_question_lists(all_questions)
        if merged:
            return merged, f"本地视觉模型分批看图解析完成（{get_local_model_settings()['provider']} / {get_local_model_settings()['vision_model']}，{len(image_paths)} 张图，批量上限 {get_vision_batch_size('reference')}）。" + "；".join(messages)
        return [], "；".join(messages)
    content, message = local_vision_chat(build_vision_extract_prompt(ocr_text), image_paths, max_images)
    if not content:
        if len(image_paths) > 1:
            midpoint = max(1, len(image_paths) // 2)
            left_questions, left_message = local_vision_extract_questions(image_paths[:midpoint], ocr_text, len(image_paths[:midpoint]), progress_callback=None)
            right_questions, right_message = local_vision_extract_questions(image_paths[midpoint:], ocr_text, len(image_paths[midpoint:]), progress_callback=None)
            merged = merge_question_lists([left_questions, right_questions])
            if merged:
                return merged, f"本地视觉模型 {len(image_paths)} 张批量请求失败，已自动拆分重试：{message}；{left_message}；{right_message}"
        return [], message
    return parse_model_questions_content(content), message


def local_vision_extract_students(image_paths, ocr_text="", max_images=None):
    content, message = local_vision_chat(build_student_vision_prompt(ocr_text), image_paths, max_images)
    if not content:
        return [], message
    return parse_model_questions_content(content), message


def local_vision_extract_submission_bundle(image_paths, ocr_text="", need_questions=False, max_images=None):
    content, message = local_vision_chat(build_submission_bundle_vision_prompt(ocr_text, need_questions), image_paths, max_images)
    if not content:
        return [], [], message
    parsed = parse_model_json_content(content)
    if isinstance(parsed, list):
        return parsed, [], message
    students = parsed.get("students") or parsed.get("学生") or []
    questions = parsed.get("questions") or parsed.get("题目") or []
    return students, questions, message


def local_llm_extract_questions(text):
    settings = get_local_model_settings()
    if not settings["enabled"]:
        return [], "本地模型解析未启用。"
    if settings["provider"] != "ollama":
        return [], f"暂只支持 Ollama 本地模型，当前 provider={settings['provider']}。"

    body = {
        "model": settings["model"],
        "stream": False,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": build_question_extract_prompt(text)},
        ],
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = (payload.get("message") or {}).get("content", "").strip()
        return parse_model_questions_content(content), f"本地模型结构化解析完成（{settings['provider']} / {settings['model']}）。"
    except Exception as error:
        return [], f"本地模型解析失败：{format_url_error(error)}"


def local_llm_extract_students(text):
    settings = get_local_model_settings()
    if not settings["enabled"]:
        return [], "本地模型解析未启用。"
    if settings["provider"] != "ollama":
        return [], f"暂只支持 Ollama 本地模型，当前 provider={settings['provider']}。"

    body = {
        "model": settings["model"],
        "stream": False,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要输出解释。"},
            {"role": "user", "content": build_student_extract_prompt(text)},
        ],
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = (payload.get("message") or {}).get("content", "").strip()
        return parse_model_questions_content(content), f"本地模型学生作答结构化完成（{settings['provider']} / {settings['model']}）。"
    except Exception as error:
        return [], f"本地模型学生作答解析失败：{format_url_error(error)}"


def llm_extract_questions(text):
    messages = []
    cloud_items, cloud_message = cloud_llm_extract_questions(text)
    messages.append(cloud_message)
    if cloud_items:
        return cloud_items, cloud_message, "cloud"

    local_items, local_message = local_llm_extract_questions(text)
    messages.append(local_message)
    if local_items:
        return local_items, "；".join(messages), "local"

    messages.append("已使用本地规则解析。")
    return [], "；".join(messages), "rule"


def split_question_text(text, chunk_size=10000, overlap=1200):
    text = str(text or "")
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    markers = [match.start() for match in re.finditer(r"\n(?:=== .*? ===|第\s*\d+\s*页|[一二三四五六七八九十]+[、.．]\s*|[0-9]{1,2}[.．、]\s*)", text)]
    boundaries = [0]
    for marker in markers:
        if marker - boundaries[-1] >= chunk_size - overlap:
            boundaries.append(marker)
    chunks = []
    start = 0
    while start < len(text):
        end_candidates = [item for item in boundaries if start + chunk_size * 0.55 <= item <= start + chunk_size]
        end = end_candidates[-1] if end_candidates else min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
        if chunks and start <= text.find(chunks[-1][:50]):
            start = end
    return chunks


def llm_extract_questions_chunked(text):
    chunks = split_question_text(text)
    if len(chunks) <= 1:
        return llm_extract_questions(text)
    all_questions = []
    messages = []
    sources = []
    for index, chunk in enumerate(chunks, start=1):
        items, message, source = llm_extract_questions(chunk)
        if items:
            all_questions.append(items)
            sources.append(source)
        messages.append(f"第{index}段：{message}")
    merged = merge_question_lists(all_questions)
    if merged:
        source = "cloud" if "cloud" in sources else sources[0] if sources else "rule"
        return merged, f"已按 {len(chunks)} 段 OCR 文本分块结构化并合并。{'；'.join(messages)}", source
    return [], "；".join(messages), "rule"


def llm_extract_students(text):
    messages = []
    cloud_items, cloud_message = cloud_llm_extract_students(text)
    messages.append(cloud_message)
    if cloud_items:
        return cloud_items, cloud_message, "cloud"

    local_items, local_message = local_llm_extract_students(text)
    messages.append(local_message)
    if local_items:
        return local_items, "；".join(messages), "local"

    messages.append("已使用本地规则解析。")
    return [], "；".join(messages), "rule"


def format_url_error(error):
    if isinstance(error, (socket.timeout, TimeoutError)) or "timed out" in str(error).lower():
        return f"请求超时：云端模型在 {get_cloud_timeout()} 秒内没有返回结果，已自动切换本地模型。"
    if isinstance(error, urllib.error.HTTPError):
        body = ""
        try:
            body = error.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        retry_after = error.headers.get("retry-after") if error.headers else None
        parts = [f"HTTP {error.code}: {error.reason}"]
        if retry_after:
            parts.append(f"retry-after={retry_after}s")
        if body:
            if "unknown variant `image_url`" in body or "expected `text`" in body:
                return "当前云端接口不支持图片输入 image_url，已回退到 OCR 文本解析。若要直接看图，需要配置支持视觉输入的模型。"
            parts.append(body[:1200])
        return " | ".join(parts)
    return str(error)


def get_cloud_timeout():
    try:
        return int(os.environ.get("CLOUD_LLM_TIMEOUT", "600"))
    except ValueError:
        return 600


def process_extract_file(tmp_path, filename, ext, target, need_questions, request_started=None, progress_callback=None):
    request_started = request_started or time.time()
    timings = []

    def update_progress(percent, stage, message):
        if progress_callback:
            progress_callback(
                {
                    "percent": max(1, min(99, int(percent))),
                    "stage": stage,
                    "message": message,
                    "elapsed": round(time.time() - request_started, 1),
                }
            )

    def mark_timing(name, started):
        timings.append({"stage": name, "seconds": round(time.time() - started, 3)})

    files = []
    sections = []
    ocr_summary = {}
    update_progress(5, "queued", "文件已接收，准备解析。")
    with tempfile.TemporaryDirectory() as vision_tmp:
        vision_images = []
        vision_limit = get_vision_total_image_limit(target, ext)
        if ext == ".zip":
            stage_started = time.time()
            update_progress(12, "zip_extract_ocr_render", "正在解包 ZIP、OCR 并渲染 PDF 页面。")
            text, files, sections, ocr_summary, vision_images = extract_zip(tmp_path, vision_tmp, vision_limit)
            mark_timing("zip_extract_ocr_render", stage_started)
            engine = "zip"
        else:
            text = ""
            engine = "macos-vision"
            if should_use_vision_first(ext, target):
                engine = "vision-first"
                ocr_summary = {}
                if ext in IMAGE_EXTS:
                    vision_images = [tmp_path]
                elif ext == ".pdf":
                    stage_started = time.time()
                    update_progress(15, "pdf_render", "正在把 PDF 渲染成视觉模型可读页面。")
                    vision_images = render_pdf_images(tmp_path, vision_tmp, vision_limit)
                    mark_timing("pdf_render", stage_started)
            else:
                stage_started = time.time()
                update_progress(12, "ocr", "正在执行 OCR 文本识别。")
                text, engine, ocr_summary = extract_plain_or_ocr(tmp_path, ext)
                mark_timing("ocr", stage_started)
                if text.strip():
                    sections = [{"name": filename, "engine": engine, "text": text.strip(), "ocr": summarize_ocr(ocr_summary)}]
            if ext in IMAGE_EXTS and not vision_images:
                vision_images = [tmp_path]
            elif ext == ".pdf" and not vision_images:
                stage_started = time.time()
                update_progress(18, "pdf_render", "正在补充渲染 PDF 页面。")
                vision_images = render_pdf_images(tmp_path, vision_tmp, vision_limit)
                mark_timing("pdf_render", stage_started)

        students = []
        if target == "submission":
            allow_student_vision = not (ext == ".zip" and len(files) > vision_limit)
            if allow_student_vision and vision_images and need_questions:
                stage_started = time.time()
                update_progress(35, "vision_submission_bundle", f"正在调用视觉模型解析学生作答和题目结构（{len(vision_images)} 页）。")
                raw_students, raw_questions, message = cloud_vision_extract_submission_bundle(vision_images, text, True, vision_limit)
                if not raw_students and not raw_questions:
                    update_progress(55, "local_vision_submission_bundle", "云端视觉未返回有效结果，正在尝试本地视觉模型。")
                    local_raw_students, local_raw_questions, local_message = local_vision_extract_submission_bundle(vision_images, text, True, vision_limit)
                    message = f"{message}；{local_message}"
                    if local_raw_students or local_raw_questions:
                        raw_students, raw_questions = local_raw_students, local_raw_questions
                mark_timing("vision_submission_bundle", stage_started)
                students = normalize_model_students(raw_students)
                question_source = "local_vision" if "本地视觉模型看图解析完成" in message else "vision"
                questions = normalize_llm_questions(raw_questions, question_source) if raw_questions else []
                llm_meta = {
                    "enabled": is_llm_configured(),
                    "model": get_vision_settings()["model"],
                    "source": "student_local_vision_bundle" if question_source == "local_vision" else "student_vision_bundle",
                    "cloud_timeout": get_cloud_timeout(),
                    "local_model": get_local_model_public_settings(),
                    "message": message,
                    "question_message": message if questions else "",
                    "question_source": question_source if questions else "",
                }
                if not students:
                    stage_started = time.time()
                    update_progress(68, "vision_student_fallback", "正在补充解析学生作答。")
                    students, fallback_meta = structure_students_from_images(vision_images, text, allow_student_vision, vision_limit)
                    mark_timing("vision_student_fallback", stage_started)
                    llm_meta["message"] = f"{message}；{fallback_meta.get('message', '')}"
                if not questions:
                    if vision_images:
                        stage_started = time.time()
                        update_progress(78, "vision_question_fallback", "正在补充解析题目和参考答案结构。")
                        questions, question_llm_meta = structure_questions_from_images(vision_images, text, vision_limit, progress_callback=update_progress)
                        mark_timing("vision_question_fallback", stage_started)
                    else:
                        stage_started = time.time()
                        update_progress(78, "text_question_fallback", "正在使用 OCR 文本补充题目结构。")
                        questions, question_llm_meta = structure_questions_from_text(text)
                        mark_timing("text_question_fallback", stage_started)
                    llm_meta["question_message"] = question_llm_meta.get("message", "")
                    llm_meta["question_source"] = question_llm_meta.get("source", "")
            else:
                stage_started = time.time()
                update_progress(35, "student_structure", "正在解析学生作答。")
                students, llm_meta = structure_students_from_images(vision_images, text, allow_student_vision, vision_limit)
                mark_timing("student_structure", stage_started)
                if need_questions:
                    if vision_images:
                        stage_started = time.time()
                        update_progress(70, "question_structure", "正在补充解析题目结构。")
                        questions, question_llm_meta = structure_questions_from_images(vision_images, text, vision_limit, progress_callback=update_progress)
                        mark_timing("question_structure", stage_started)
                    else:
                        stage_started = time.time()
                        update_progress(70, "question_structure", "正在使用 OCR 文本补充题目结构。")
                        questions, question_llm_meta = structure_questions_from_text(text)
                        mark_timing("question_structure", stage_started)
                    llm_meta["question_message"] = question_llm_meta.get("message", "")
                    llm_meta["question_source"] = question_llm_meta.get("source", "")
                else:
                    questions = []
            if not students and not text and ext in OCR_EXTS:
                stage_started = time.time()
                update_progress(82, "ocr_fallback", "正在执行 OCR 回退解析。")
                text, engine, ocr_summary = extract_plain_or_ocr(tmp_path, ext)
                mark_timing("ocr_fallback", stage_started)
                if text.strip():
                    sections = [{"name": filename, "engine": engine, "text": text.strip(), "ocr": summarize_ocr(ocr_summary)}]
                    stage_started = time.time()
                    update_progress(88, "text_student_fallback", "正在使用 OCR 文本解析学生作答。")
                    students, fallback_meta = structure_students_from_text(text)
                    mark_timing("text_student_fallback", stage_started)
                    llm_meta["message"] = f"{llm_meta.get('message', '')}；{fallback_meta.get('message', '')}"
            if not text and students:
                text = students_to_readable_text(students)
            else:
                text = text or ""
        elif vision_images:
            stage_started = time.time()
            update_progress(35, "question_structure", f"正在调用视觉模型分批解析题目和答案（{len(vision_images)} 页）。")
            questions, llm_meta = structure_questions_from_images(vision_images, text, vision_limit, progress_callback=update_progress)
            mark_timing("question_structure", stage_started)
            initial_question_meta = dict(llm_meta or {})
            if (not questions or is_question_extraction_too_weak(questions, text)) and not text and ext in OCR_EXTS:
                stage_started = time.time()
                update_progress(74, "ocr_fallback", "视觉解析结果不足，正在执行 OCR 回退。")
                text, engine, ocr_summary = extract_plain_or_ocr(tmp_path, ext)
                mark_timing("ocr_fallback", stage_started)
                if text.strip():
                    sections = [{"name": filename, "engine": engine, "text": text.strip(), "ocr": summarize_ocr(ocr_summary)}]
                    stage_started = time.time()
                    update_progress(84, "text_question_fallback", "正在用 OCR 文本分块补全题目和答案。")
                    questions, llm_meta = structure_questions_from_text(text)
                    mark_timing("text_question_fallback", stage_started)
                    previous_message = initial_question_meta.get("message", "")
                    if previous_message:
                        llm_meta["message"] = f"{previous_message}；已使用 OCR 文本回退解析。{llm_meta.get('message', '')}"
            elif is_question_extraction_too_weak(questions, text) and text.strip():
                stage_started = time.time()
                update_progress(84, "text_question_fallback", "正在用 OCR 文本分块补全题目和答案。")
                fallback_questions, fallback_meta = structure_questions_from_text(text)
                mark_timing("text_question_fallback", stage_started)
                if len(fallback_questions) > len(questions):
                    questions = fallback_questions
                    llm_meta = fallback_meta
                    previous_message = initial_question_meta.get("message", "")
                    if previous_message:
                        llm_meta["message"] = f"{previous_message}；已使用 OCR 文本回退解析。{llm_meta.get('message', '')}"
            if not text and questions:
                text = questions_to_readable_text(questions)
        else:
            stage_started = time.time()
            update_progress(45, "question_structure", "正在使用文本模型解析题目和答案。")
            questions, llm_meta = structure_questions_from_text(text)
            mark_timing("question_structure", stage_started)
    timings.append({"stage": "total", "seconds": round(time.time() - request_started, 3)})
    update_progress(99, "finalizing", "正在整理解析结果。")
    return {
        "ok": True,
        "filename": filename,
        "target": target,
        "engine": engine,
        "text": text,
        "ocr": summarize_ocr(ocr_summary),
        "files": files,
        "sections": sections,
        "questions": questions,
        "students": students,
        "llm": llm_meta,
        "timings": timings,
        "warning": "" if (questions or students or target == "submission") else "已提取文本，但未自动识别出标准答案。请检查 OCR 文本或上传结构化文件。",
    }


def create_extract_job(tmp_path, filename, ext, target, need_questions):
    job_id = uuid.uuid4().hex
    initial_progress = {
        "percent": 1,
        "stage": "queued",
        "message": "文件已上传，等待后台解析。",
        "elapsed": 0,
    }
    with EXTRACT_JOBS_LOCK:
        EXTRACT_JOBS[job_id] = {
            "status": "processing",
            "filename": filename,
            "target": target,
            "created_at": time.time(),
            "updated_at": time.time(),
            "progress": initial_progress,
        }

    def update_job_progress(progress):
        with EXTRACT_JOBS_LOCK:
            job = EXTRACT_JOBS.get(job_id) or {}
            if not job:
                return
            job["progress"] = progress
            job["updated_at"] = time.time()
            EXTRACT_JOBS[job_id] = job

    def run_job():
        try:
            payload = process_extract_file(tmp_path, filename, ext, target, need_questions, progress_callback=update_job_progress)
            payload["job_id"] = job_id
            with EXTRACT_JOBS_LOCK:
                EXTRACT_JOBS[job_id] = {
                    "status": "done",
                    "filename": filename,
                    "target": target,
                    "created_at": EXTRACT_JOBS.get(job_id, {}).get("created_at", time.time()),
                    "updated_at": time.time(),
                    "progress": {
                        "percent": 100,
                        "stage": "done",
                        "message": "解析完成。",
                        "elapsed": round(time.time() - EXTRACT_JOBS.get(job_id, {}).get("created_at", time.time()), 1),
                    },
                    "result": payload,
                }
        except (RuntimeError, zipfile.BadZipFile, ValueError) as error:
            with EXTRACT_JOBS_LOCK:
                EXTRACT_JOBS[job_id] = {
                    "status": "error",
                    "filename": filename,
                    "target": target,
                    "created_at": EXTRACT_JOBS.get(job_id, {}).get("created_at", time.time()),
                    "updated_at": time.time(),
                    "error": str(error),
                    "engine": "zip" if ext == ".zip" else "macos-vision",
                    "progress": {
                        "percent": 100,
                        "stage": "error",
                        "message": str(error),
                        "elapsed": round(time.time() - EXTRACT_JOBS.get(job_id, {}).get("created_at", time.time()), 1),
                    },
                }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    threading.Thread(target=run_job, daemon=True).start()
    return job_id


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            print("Client disconnected before response was sent.")

    def request_path(self):
        return urllib.parse.urlparse(self.path).path

    def is_local_request(self):
        client_host = self.client_address[0] if self.client_address else ""
        host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
        return client_host in ("127.0.0.1", "::1", "localhost") or host in ("127.0.0.1", "::1", "localhost")

    def is_authenticated(self):
        if not is_access_control_enabled():
            return True
        if self.is_local_request():
            return True
        cookies = parse_cookie_header(self.headers.get("Cookie"))
        return cookies.get(ACCESS_COOKIE_NAME) == build_access_token()

    def send_login_page(self):
        body = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 作业批改访问验证</title>
    <style>
      :root {{
        color-scheme: light;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f4f7fb;
        color: #152332;
      }}
      body {{
        min-height: 100vh;
        margin: 0;
        display: grid;
        place-items: center;
      }}
      main {{
        width: min(420px, calc(100vw - 40px));
        padding: 32px;
        border: 1px solid #d6e2ee;
        border-radius: 12px;
        background: #ffffff;
        box-shadow: 0 18px 60px rgba(20, 42, 70, 0.12);
      }}
      h1 {{
        margin: 0 0 8px;
        font-size: 28px;
      }}
      p {{
        margin: 0 0 24px;
        color: #5d7185;
        line-height: 1.7;
      }}
      label {{
        display: block;
        margin-bottom: 8px;
        font-weight: 700;
      }}
      input {{
        box-sizing: border-box;
        width: 100%;
        height: 48px;
        padding: 0 14px;
        border: 1px solid #bdd0e2;
        border-radius: 8px;
        font-size: 18px;
      }}
      button {{
        width: 100%;
        height: 48px;
        margin-top: 16px;
        border: 0;
        border-radius: 8px;
        background: #008f7a;
        color: #fff;
        font-size: 17px;
        font-weight: 700;
        cursor: pointer;
      }}
      .error {{
        min-height: 24px;
        margin-top: 12px;
        color: #c62828;
        font-weight: 700;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>访问验证</h1>
      <p>请输入访问密码后进入 AI 作业批改工作台。</p>
      <form id="loginForm">
        <label for="password">访问密码</label>
        <input id="password" name="password" type="password" autocomplete="current-password" autofocus />
        <button type="submit">进入工作台</button>
        <div class="error" id="error"></div>
      </form>
    </main>
    <script>
      document.getElementById("loginForm").addEventListener("submit", async (event) => {{
        event.preventDefault();
        const error = document.getElementById("error");
        error.textContent = "";
        const password = document.getElementById("password").value;
        const response = await fetch("/api/login", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ password }})
        }});
        if (response.ok) {{
          window.location.href = "/";
          return;
        }}
        error.textContent = "密码不正确，请重新输入。";
      }});
    </script>
  </body>
</html>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_login(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "JSON 格式错误"})
            return
        if str(payload.get("password") or "") != get_access_password():
            self.send_json(401, {"ok": False, "error": "访问密码错误"})
            return
        cookie = (
            f"{ACCESS_COOKIE_NAME}={build_access_token()}; Path=/; HttpOnly; "
            "SameSite=Lax; Max-Age=604800"
        )
        self.send_json(200, {"ok": True}, {"Set-Cookie": cookie})

    def handle_logout(self):
        cookie = f"{ACCESS_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        self.send_json(200, {"ok": True}, {"Set-Cookie": cookie})

    def do_GET(self):
        path = self.request_path()
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/auth-status":
            self.send_json(
                200,
                {
                    "ok": True,
                    "auth_enabled": is_access_control_enabled(),
                    "authenticated": self.is_authenticated(),
                },
            )
            return
        if not self.is_authenticated():
            if path.startswith("/api/"):
                self.send_json(401, {"ok": False, "error": "请先输入访问密码"})
                return
            self.send_login_page()
            return
        if path == "/api/extract-status":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            job_id = (query.get("job_id") or [""])[0]
            with EXTRACT_JOBS_LOCK:
                job = dict(EXTRACT_JOBS.get(job_id) or {})
            if not job:
                self.send_json(404, {"ok": False, "error": "解析任务不存在或已过期"})
                return
            if job.get("status") == "done":
                self.send_json(200, job.get("result") or {"ok": False, "error": "解析结果为空"})
                return
            if job.get("status") == "error":
                self.send_json(
                    500,
                    {
                        "ok": False,
                        "error": job.get("error") or "解析任务失败",
                        "engine": job.get("engine") or "macos-vision",
                        "status": "error",
                    },
                )
                return
            self.send_json(
                200,
                {
                    "ok": True,
                    "status": "processing",
                    "job_id": job_id,
                    "filename": job.get("filename", ""),
                    "target": job.get("target", ""),
                    "elapsed": round(time.time() - job.get("created_at", time.time()), 1),
                    "progress": job.get("progress") or {},
                },
            )
            return
        if path == "/api/health":
            llm_settings = get_llm_settings()
            vision_settings = get_vision_settings()
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "ai-grading-mvp",
                    "ocr": "macos-vision",
                    "llm": {
                        "configured": is_llm_configured(),
                        "enabled": MODEL_CONFIG.get("enabled", True),
                        "model": llm_settings.get("model", ""),
                        "api_url": llm_settings.get("api_url", ""),
                        "api_key_env": llm_settings.get("api_key_env", "OPENAI_API_KEY"),
                        "cloud_timeout": get_cloud_timeout(),
                        "vision_model": {
                            "enabled": vision_settings.get("enabled", False),
                            "model": vision_settings.get("model", ""),
                            "api_url": vision_settings.get("api_url", ""),
                            "max_images": get_vision_max_images(),
                            "max_images_reference": get_vision_max_images("reference"),
                            "max_images_submission": get_vision_max_images("submission"),
                            "max_total_images_reference_zip": get_vision_total_image_limit("reference", ".zip"),
                            "batch_size_reference": get_vision_batch_size("reference"),
                            "batch_max_mb_reference": round(get_vision_batch_max_bytes("reference") / 1024 / 1024, 1),
                            "image_max_dim": get_vision_image_max_dim(),
                        },
                        "local_model": get_local_model_public_settings(),
                    },
                    "supports": sorted(ALLOWED_EXTS),
                },
            )
            return
        if path == "/api/llm-test":
            self.send_json(200, test_llm_connection())
            return
        if path == "/api/vision-test":
            self.send_json(200, test_vision_model_connection())
            return
        super().do_GET()

    def do_POST(self):
        path = self.request_path()
        if path == "/api/login":
            self.handle_login()
            return
        if path == "/api/logout":
            self.handle_logout()
            return
        if not self.is_authenticated():
            self.send_json(401, {"ok": False, "error": "请先输入访问密码"})
            return

        request_started = time.time()
        timings = []

        def mark_timing(name, started):
            timings.append({"stage": name, "seconds": round(time.time() - started, 3)})

        if path == "/api/structure-text":
            self.handle_structure_text()
            return
        if path != "/api/extract":
            self.send_error(404)
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json(400, {"ok": False, "error": "请使用 multipart/form-data 上传文件"})
            return

        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        file_item = form["file"] if "file" in form else None
        target = "reference"
        if "target" in form:
            target = str(getattr(form["target"], "value", "") or "reference").strip().lower()
        if target not in ("reference", "submission"):
            target = "reference"
        need_questions = False
        if "need_questions" in form:
            need_questions = str(getattr(form["need_questions"], "value", "")).strip().lower() in ("1", "true", "yes")
        async_extract = False
        if "async" in form:
            async_extract = str(getattr(form["async"], "value", "")).strip().lower() in ("1", "true", "yes")
        if file_item is None or not getattr(file_item, "filename", ""):
            self.send_json(400, {"ok": False, "error": "缺少上传文件"})
            return

        filename = os.path.basename(file_item.filename)
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            self.send_json(400, {"ok": False, "error": f"暂不支持 {ext or '未知'} 文件"})
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(file_item.file.read())
            tmp_path = tmp.name

        if async_extract:
            job_id = create_extract_job(tmp_path, filename, ext, target, need_questions)
            self.send_json(
                202,
                {
                    "ok": True,
                    "status": "processing",
                    "job_id": job_id,
                    "filename": filename,
                    "target": target,
                    "message": "文件已上传，正在后台解析。",
                },
            )
            return

        try:
            files = []
            sections = []
            ocr_summary = {}
            with tempfile.TemporaryDirectory() as vision_tmp:
                vision_images = []
                vision_limit = get_vision_total_image_limit(target, ext)
                if ext == ".zip":
                    stage_started = time.time()
                    text, files, sections, ocr_summary, vision_images = extract_zip(tmp_path, vision_tmp, vision_limit)
                    mark_timing("zip_extract_ocr_render", stage_started)
                    engine = "zip"
                else:
                    text = ""
                    engine = "macos-vision"
                    if should_use_vision_first(ext, target):
                        engine = "vision-first"
                        ocr_summary = {}
                        if ext in IMAGE_EXTS:
                            vision_images = [tmp_path]
                        elif ext == ".pdf":
                            stage_started = time.time()
                            vision_images = render_pdf_images(tmp_path, vision_tmp, vision_limit)
                            mark_timing("pdf_render", stage_started)
                    else:
                        stage_started = time.time()
                        text, engine, ocr_summary = extract_plain_or_ocr(tmp_path, ext)
                        mark_timing("ocr", stage_started)
                        if text.strip():
                            sections = [{"name": filename, "engine": engine, "text": text.strip(), "ocr": summarize_ocr(ocr_summary)}]
                    if ext in IMAGE_EXTS and not vision_images:
                        vision_images = [tmp_path]
                    elif ext == ".pdf" and not vision_images:
                        stage_started = time.time()
                        vision_images = render_pdf_images(tmp_path, vision_tmp, vision_limit)
                        mark_timing("pdf_render", stage_started)

                students = []
                if target == "submission":
                    allow_student_vision = not (ext == ".zip" and len(files) > vision_limit)
                    if allow_student_vision and vision_images and need_questions:
                        stage_started = time.time()
                        raw_students, raw_questions, message = cloud_vision_extract_submission_bundle(vision_images, text, True, vision_limit)
                        if not raw_students and not raw_questions:
                            local_raw_students, local_raw_questions, local_message = local_vision_extract_submission_bundle(vision_images, text, True, vision_limit)
                            message = f"{message}；{local_message}"
                            if local_raw_students or local_raw_questions:
                                raw_students, raw_questions = local_raw_students, local_raw_questions
                        mark_timing("vision_submission_bundle", stage_started)
                        students = normalize_model_students(raw_students)
                        question_source = "local_vision" if "本地视觉模型看图解析完成" in message else "vision"
                        questions = normalize_llm_questions(raw_questions, question_source) if raw_questions else []
                        llm_meta = {
                            "enabled": is_llm_configured(),
                            "model": get_vision_settings()["model"],
                            "source": "student_local_vision_bundle" if question_source == "local_vision" else "student_vision_bundle",
                            "cloud_timeout": get_cloud_timeout(),
                            "local_model": get_local_model_public_settings(),
                            "message": message,
                            "question_message": message if questions else "",
                            "question_source": question_source if questions else "",
                        }
                        if not students:
                            stage_started = time.time()
                            students, fallback_meta = structure_students_from_images(vision_images, text, allow_student_vision, vision_limit)
                            mark_timing("vision_student_fallback", stage_started)
                            llm_meta["message"] = f"{message}；{fallback_meta.get('message', '')}"
                        if not questions:
                            if vision_images:
                                stage_started = time.time()
                                questions, question_llm_meta = structure_questions_from_images(vision_images, text, vision_limit)
                                mark_timing("vision_question_fallback", stage_started)
                            else:
                                stage_started = time.time()
                                questions, question_llm_meta = structure_questions_from_text(text)
                                mark_timing("text_question_fallback", stage_started)
                            llm_meta["question_message"] = question_llm_meta.get("message", "")
                            llm_meta["question_source"] = question_llm_meta.get("source", "")
                    else:
                        stage_started = time.time()
                        students, llm_meta = structure_students_from_images(vision_images, text, allow_student_vision, vision_limit)
                        mark_timing("student_structure", stage_started)
                        if need_questions:
                            if vision_images:
                                stage_started = time.time()
                                questions, question_llm_meta = structure_questions_from_images(vision_images, text, vision_limit)
                                mark_timing("question_structure", stage_started)
                            else:
                                stage_started = time.time()
                                questions, question_llm_meta = structure_questions_from_text(text)
                                mark_timing("question_structure", stage_started)
                            llm_meta["question_message"] = question_llm_meta.get("message", "")
                            llm_meta["question_source"] = question_llm_meta.get("source", "")
                        else:
                            questions = []
                    if not students and not text and ext in OCR_EXTS:
                        stage_started = time.time()
                        text, engine, ocr_summary = extract_plain_or_ocr(tmp_path, ext)
                        mark_timing("ocr_fallback", stage_started)
                        if text.strip():
                            sections = [{"name": filename, "engine": engine, "text": text.strip(), "ocr": summarize_ocr(ocr_summary)}]
                            stage_started = time.time()
                            students, fallback_meta = structure_students_from_text(text)
                            mark_timing("text_student_fallback", stage_started)
                            llm_meta["message"] = f"{llm_meta.get('message', '')}；{fallback_meta.get('message', '')}"
                    if not text and students:
                        text = students_to_readable_text(students)
                    else:
                        text = text or ""
                elif vision_images:
                    stage_started = time.time()
                    questions, llm_meta = structure_questions_from_images(vision_images, text, vision_limit)
                    mark_timing("question_structure", stage_started)
                    initial_question_meta = dict(llm_meta or {})
                    if (not questions or is_question_extraction_too_weak(questions, text)) and not text and ext in OCR_EXTS:
                        stage_started = time.time()
                        text, engine, ocr_summary = extract_plain_or_ocr(tmp_path, ext)
                        mark_timing("ocr_fallback", stage_started)
                        if text.strip():
                            sections = [{"name": filename, "engine": engine, "text": text.strip(), "ocr": summarize_ocr(ocr_summary)}]
                            stage_started = time.time()
                            questions, llm_meta = structure_questions_from_text(text)
                            mark_timing("text_question_fallback", stage_started)
                            previous_message = initial_question_meta.get("message", "")
                            if previous_message:
                                llm_meta["message"] = f"{previous_message}；已使用 OCR 文本回退解析。{llm_meta.get('message', '')}"
                    elif is_question_extraction_too_weak(questions, text) and text.strip():
                        stage_started = time.time()
                        fallback_questions, fallback_meta = structure_questions_from_text(text)
                        mark_timing("text_question_fallback", stage_started)
                        if len(fallback_questions) > len(questions):
                            questions = fallback_questions
                            llm_meta = fallback_meta
                            previous_message = initial_question_meta.get("message", "")
                            if previous_message:
                                llm_meta["message"] = f"{previous_message}；已使用 OCR 文本回退解析。{llm_meta.get('message', '')}"
                    if not text and questions:
                        text = questions_to_readable_text(questions)
                else:
                    stage_started = time.time()
                    questions, llm_meta = structure_questions_from_text(text)
                    mark_timing("question_structure", stage_started)
            timings.append({"stage": "total", "seconds": round(time.time() - request_started, 3)})
            self.send_json(
                200,
                {
                    "ok": True,
                    "filename": filename,
                    "target": target,
                    "engine": engine,
                    "text": text,
                    "ocr": summarize_ocr(ocr_summary),
                    "files": files,
                    "sections": sections,
                    "questions": questions,
                    "students": students,
                    "llm": llm_meta,
                    "timings": timings,
                    "warning": "" if (questions or students or target == "submission") else "已提取文本，但未自动识别出标准答案。请检查 OCR 文本或上传结构化文件。",
                },
            )
        except (RuntimeError, zipfile.BadZipFile, ValueError) as error:
            self.send_json(
                500,
                {
                    "ok": False,
                    "error": str(error),
                    "engine": "zip" if ext == ".zip" else "macos-vision",
                },
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def handle_structure_text(self):
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            self.send_json(400, {"ok": False, "error": "请使用 application/json 提交 OCR 文本"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            text = str(payload.get("text") or "")
            target = str(payload.get("target") or "reference").strip().lower()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "JSON 格式错误"})
            return
        if not text.strip():
            self.send_json(400, {"ok": False, "error": "OCR 文本不能为空"})
            return
        if target == "submission":
            students, llm_meta = structure_students_from_text(text)
            self.send_json(
                200,
                {
                    "ok": True,
                    "text": text,
                    "target": target,
                    "students": students,
                    "llm": llm_meta,
                    "warning": "" if students else "大模型未识别出学生作答，请继续修正 OCR 文本或重新上传更清晰图片。",
                },
            )
            return
        questions, llm_meta = structure_questions_from_text(text)
        self.send_json(
            200,
            {
                "ok": True,
                "text": text,
                "target": "reference",
                "questions": questions,
                "llm": llm_meta,
                "warning": "" if questions else "大模型未识别出题目/答案，请继续修正 OCR 文本或使用结构化文件。",
            },
        )


def normalize_llm_questions(items, source="llm"):
    normalized = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or item.get("question_id") or item.get("题号") or f"q{index + 1}")
        no = re.sub(r"^q", "", raw_id, flags=re.I)
        no = normalize_no(no)
        qtype = item.get("type") or item.get("题型") or ""
        title = item.get("title") or item.get("题目") or item.get("stem") or item.get("题干") or f"第 {no} 题"
        answer = item.get("answer") or item.get("答案") or ""
        raw_rubric = item.get("rubric") or item.get("评分点") or item.get("criteria") or item.get("采分点") or []
        raw_keywords = item.get("keywords") or item.get("关键词") or item.get("knowledge") or item.get("知识点") or []
        score = item.get("score") or item.get("分值") or item.get("points") or 0
        score_context = " ".join(
            str(part)
            for part in [
                title,
                item.get("stem") or item.get("题干") or "",
                answer,
                raw_rubric,
                raw_keywords,
                item.get("analysis") or item.get("解析") or "",
            ]
        )
        normalized_score = normalize_score(score, qtype, no, score_context)
        rubric = split_structured_list(raw_rubric)
        keywords = split_structured_list(raw_keywords)
        if not rubric:
            rubric = extract_explicit_rubric_from_answer(answer)
        normalized.append(
            {
                "id": f"q{no}",
                "subject": item.get("subject", ""),
                "type": qtype,
                "title": title,
                "answer": answer,
                "score": normalized_score,
                "keywords": keywords,
                "rubric": rubric,
                "visual_notes": item.get("visual_notes") or item.get("图形说明") or item.get("图形关系") or "",
                "source": source,
            }
        )
    return sync_parent_answers_from_subquestions(normalized)


def split_structured_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in re.split(r"[、,，;；|/\n]", str(value)) if item.strip()]


def normalize_score(score, question_type="", question_no="", context=""):
    authoritative = infer_score_from_text(context, authoritative=True)
    if authoritative:
        return authoritative
    try:
        value = float(score)
        if value > 0:
            return int(value) if value.is_integer() else value
    except (TypeError, ValueError):
        pass
    inferred = infer_score_from_text(context, authoritative=False)
    if inferred:
        return inferred
    return 0


def infer_score_from_text(text, authoritative=False):
    compact = re.sub(r"\s+", "", str(text or ""))
    patterns = [
        r"本小题满分([0-9]{1,2}(?:\.[0-9])?)分",
        r"小题满分([0-9]{1,2}(?:\.[0-9])?)分",
        r"满分([0-9]{1,2}(?:\.[0-9])?)分",
        r"[（(]([0-9]{1,2}(?:\.[0-9])?)分[）)]",
    ]
    if not authoritative:
        patterns.append(r"共([0-9]{1,2}(?:\.[0-9])?)分")
    values = []
    for pattern in patterns:
        for match in re.finditer(pattern, compact):
            value = float(match.group(1))
            if 0 < value <= 100:
                values.append(int(value) if value.is_integer() else value)
    return max(values) if values else 0


def extract_explicit_rubric_from_answer(answer):
    text = str(answer or "").strip()
    if not text:
        return []
    if re.fullmatch(r"[A-Da-d对错√×真假]|-?\d+(?:\.\d+)?", text):
        return []
    scored = [
        f"{content.strip()}（{score}分）"
        for content, score in re.findall(r"([^。；;\n]{2,80}?)[（(]([0-9]{1,2}(?:\.[0-9])?)分[）)]", text)
        if content.strip()
    ]
    if scored:
        return scored[:6]
    return []


def normalize_model_students(items):
    normalized = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        student = str(item.get("student") or item.get("学生") or item.get("name") or item.get("姓名") or f"学生{index + 1}").strip()
        raw_answers = item.get("answers") or item.get("作答") or item.get("答案") or {}
        answers = {}
        if isinstance(raw_answers, dict):
            for key, value in raw_answers.items():
                raw_key = str(key).strip()
                qid = raw_key if raw_key.lower().startswith("q") else f"q{normalize_no(raw_key)}"
                answers[qid] = str(value).strip()
        elif isinstance(raw_answers, list):
            for answer_item in raw_answers:
                if not isinstance(answer_item, dict):
                    continue
                raw_key = answer_item.get("id") or answer_item.get("question_id") or answer_item.get("题号")
                if not raw_key:
                    continue
                qid = str(raw_key).strip()
                if not qid.lower().startswith("q"):
                    qid = f"q{normalize_no(qid)}"
                answers[qid] = str(answer_item.get("answer") or answer_item.get("作答") or answer_item.get("答案") or "").strip()
        if answers:
            normalized.append({"student": student or f"学生{index + 1}", "answers": answers})
    return normalized


def is_llm_configured():
    if not MODEL_CONFIG.get("enabled", True):
        return False
    api_key_env = MODEL_CONFIG.get("api_key_env") or "OPENAI_API_KEY"
    return bool(
        os.environ.get("LLM_API_KEY")
        or os.environ.get(api_key_env)
        or MODEL_CONFIG.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
    )


def get_local_model_public_settings():
    settings = get_local_model_settings()
    return {
        "enabled": settings["enabled"],
        "provider": settings["provider"],
        "api_url": settings["api_url"],
        "model": settings["model"],
        "vision_enabled": settings["vision_enabled"],
        "vision_model": settings["vision_model"],
    }


def get_llm_settings():
    api_key_env = MODEL_CONFIG.get("api_key_env") or "OPENAI_API_KEY"
    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get(api_key_env)
        or MODEL_CONFIG.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
    )
    return {
        "api_key": api_key,
        "api_key_env": api_key_env,
        "api_url": os.environ.get("LLM_API_URL") or MODEL_CONFIG.get("api_url", "https://api.openai.com/v1/chat/completions"),
        "model": os.environ.get("LLM_MODEL") or MODEL_CONFIG.get("model", "gpt-4o-mini"),
    }


def test_llm_connection():
    local_result = test_local_model_connection()
    if not MODEL_CONFIG.get("enabled", True):
        return {"ok": local_result.get("ok", False), "effective": "local" if local_result.get("ok") else "rule", "cloud": {"ok": False, "configured": False, "error": "云端大模型解析未启用"}, "local": local_result}
    settings = get_llm_settings()
    if not settings["api_key"]:
        return {"ok": local_result.get("ok", False), "effective": "local" if local_result.get("ok") else "rule", "cloud": {"ok": False, "configured": False, "error": f"未配置 {settings['api_key_env']}/LLM_API_KEY"}, "local": local_result}
    body = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": "只输出 OK"},
            {"role": "user", "content": "请输出 OK"},
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "ok": True,
            "effective": "cloud",
            "cloud": {
                "ok": True,
                "configured": True,
                "model": settings["model"],
                "api_url": settings["api_url"],
                "timeout": get_cloud_timeout(),
                "response": content,
            },
            "local": local_result,
        }
    except Exception as error:
        return {
            "ok": local_result.get("ok", False),
            "effective": "local" if local_result.get("ok") else "rule",
            "cloud": {
                "ok": False,
                "configured": True,
                "model": settings["model"],
                "api_url": settings["api_url"],
                "timeout": get_cloud_timeout(),
                "error": format_url_error(error),
            },
            "local": local_result,
        }


def test_vision_model_connection():
    settings = get_vision_settings()
    public_settings = {
        "enabled": settings.get("enabled", False),
        "configured": bool(settings.get("api_key")),
        "model": settings.get("model", ""),
        "api_url": settings.get("api_url", ""),
        "max_images": get_vision_max_images(),
    }
    if not settings["enabled"]:
        return {"ok": False, "error": "视觉模型解析未启用", **public_settings}
    if not settings["api_key"]:
        return {"ok": False, "error": "未配置视觉模型 API key", **public_settings}

    tiny_png = (
        "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAVUlEQVR4nO2WMQ4A"
        "IAgDqfH/X8bBVS3EoEtvJYFQKAHubpW00uymAgE0A0rfBQBYkqWl/nUw8ZjPD+"
        "1qiyiSiCKJKJLo9tghf7RfzwB6vBjyAaVcogHmfQxChL7X8QAAAABJRU5ErkJggg=="
    )
    body = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": "只输出 OK，不要输出其他内容。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请看这张测试图片，并只输出 OK。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{tiny_png}"}},
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": 16,
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60, context=https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "response": content, **public_settings}
    except Exception as error:
        return {"ok": False, "error": format_url_error(error), **public_settings}


def test_local_model_connection():
    settings = get_local_model_settings()
    if not settings["enabled"]:
        return {"ok": False, "configured": False, "error": "本地模型解析未启用", **get_local_model_public_settings()}
    if settings["provider"] != "ollama":
        return {"ok": False, "configured": False, "error": f"暂只支持 Ollama，本地 provider={settings['provider']}", **get_local_model_public_settings()}
    body = {
        "model": settings["model"],
        "stream": False,
        "messages": [
            {"role": "system", "content": "只输出 OK"},
            {"role": "user", "content": "请输出 OK"},
        ],
        "options": {"temperature": 0, "num_predict": 8},
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = (payload.get("message") or {}).get("content", "")
        vision_result = test_local_vision_model_connection()
        return {"ok": True, "configured": True, "response": content, "vision": vision_result, **get_local_model_public_settings()}
    except Exception as error:
        vision_result = test_local_vision_model_connection()
        return {"ok": False, "configured": True, "error": format_url_error(error), "vision": vision_result, **get_local_model_public_settings()}


def test_local_vision_model_connection():
    settings = get_local_model_settings()
    public_settings = {
        "enabled": settings["vision_enabled"],
        "provider": settings["provider"],
        "api_url": settings["api_url"],
        "model": settings["vision_model"],
    }
    if not settings["enabled"] or not settings["vision_enabled"]:
        return {"ok": False, "configured": False, "error": "本地视觉模型解析未启用", **public_settings}
    if settings["provider"] != "ollama":
        return {"ok": False, "configured": False, "error": f"暂只支持 Ollama，本地 provider={settings['provider']}", **public_settings}

    tiny_png = (
        "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAVUlEQVR4nO2WMQ4A"
        "IAgDqfH/X8bBVS3EoEtvJYFQKAHubpW00uymAgE0A0rfBQBYkqWl/nUw8ZjPD+"
        "1qiyiSiCKJKJLo9tghf7RfzwB6vBjyAaVcogHmfQxChL7X8QAAAABJRU5ErkJggg=="
    )
    body = {
        "model": settings["vision_model"],
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": "请看这张测试图片，并只输出 OK。",
                "images": [tiny_png],
            }
        ],
        "options": {"temperature": 0, "num_predict": 8},
    }
    request = urllib.request.Request(
        settings["api_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = (payload.get("message") or {}).get("content", "")
        return {"ok": True, "configured": True, "response": content, **public_settings}
    except Exception as error:
        return {"ok": False, "configured": True, "error": format_url_error(error), **public_settings}


def main():
    os.chdir(ROOT)
    requested_port = int(os.environ.get("PORT", "8011"))
    server = None
    port = requested_port
    for candidate in range(requested_port, requested_port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError as error:
            if error.errno not in (48, 98) and getattr(error, "winerror", None) != 10048:
                raise
    if server is None:
        raise OSError(f"无法在 {requested_port}-{requested_port + 19} 范围内找到可用端口")
    if port != requested_port:
        print(f"Port {requested_port} is busy, using {port} instead.")
    print(f"Serving AI grading MVP at http://127.0.0.1:{port}")
    if is_access_control_enabled():
        print(f"Access password: enabled (set ACCESS_PASSWORD in .env to change it)")
    else:
        print("Access password: disabled")
    print(f"Public tunnel command: cloudflared tunnel --protocol http2 --url http://127.0.0.1:{port}")
    llm_status = "enabled" if is_llm_configured() else "not configured"
    llm_settings = get_llm_settings()
    print(f"LLM parser: {llm_status} ({llm_settings.get('model', '')} @ {llm_settings.get('api_url', '')})")
    server.serve_forever()


if __name__ == "__main__":
    main()
