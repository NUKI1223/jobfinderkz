"""Worker composition root; workflows remain import-compatible for integrations."""
import httpx
from . import ai, ingest
from .workflows.output import result_record
from .workflows.resumes import parse_cv, rank, fact_catalog
from .workflows.documents import document
from .workflows.interviews import plan, evaluate, audio_answer
from .workflows.knowledge import import_source, extract_questions, import_material, index_knowledge
from .workflows.vacancies import hh_sync

HANDLERS = {'parse_cv': parse_cv, 'rank': rank, 'document': document, 'plan': plan, 'evaluate': evaluate,
    'audio_answer': audio_answer, 'import_source': import_source, 'extract_questions': extract_questions,
    'import_material': import_material, 'index_knowledge': index_knowledge, 'hh_sync': hh_sync}
