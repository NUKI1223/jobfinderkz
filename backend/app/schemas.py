from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

Direction = Literal['frontend', 'python', 'qa']
Level = Literal['junior', 'middle']
Language = Literal['ru', 'en']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Credentials(Strict):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator('email')
    @classmethod
    def email_valid(cls, v):
        v = v.strip().lower()
        if '@' not in v or '.' not in v.split('@')[-1] or ' ' in v:
            raise ValueError('Укажите корректный email')
        return v


class Profile(Strict):
    direction: Direction = 'frontend'
    level: Level = 'junior'
    regions: list[str] = Field(default_factory=lambda: ['Казахстан'], max_length=20)
    work_format: Literal['remote', 'office', 'hybrid', 'any'] = 'any'
    language: Language = 'ru'


class CVFacts(Strict):
    summary: str = Field(max_length=6000)
    skills: list[str] = Field(max_length=100)
    experience: list[str] = Field(max_length=50)
    education: list[str] = Field(max_length=30)
    projects: list[str] = Field(max_length=50)
    languages: list[str] = Field(max_length=20)


class CVText(Strict):
    text: str = Field(min_length=40, max_length=60000)


class VacancyInput(Strict):
    title: str = Field(min_length=2, max_length=250)
    company: str = Field(default='', max_length=250)
    description: str = Field(min_length=30, max_length=40000)
    url: str = Field(default='', max_length=2000)
    direction: Direction = 'frontend'
    level: Level = 'junior'
    region: str = Field(default='Казахстан', max_length=200)
    work_format: Literal['remote', 'office', 'hybrid', 'any'] = 'any'

    @field_validator('url')
    @classmethod
    def safe_link(cls, v):
        from urllib.parse import urlsplit
        if v and (urlsplit(v).scheme not in ('https', 'http') or not urlsplit(v).hostname):
            raise ValueError('Нужна ссылка http/https')
        return v


class DocumentRequest(Strict):
    vacancy_id: str
    cv_id: str
    kind: Literal['cover_letter', 'adapted_cv']
    language: Language = 'ru'


class DocumentResult(Strict):
    title: str
    # AI selects verbatim facts; only the connective prose can be generated.
    introduction: str
    selected_fact_ids: list[str]
    closing: str
    changes: list[str]


class EditText(Strict):
    text: str = Field(min_length=1, max_length=60000)


class Match(Strict):
    vacancy_id: str
    score: int = Field(ge=0, le=100)
    reasons: list[str]
    matching_skills: list[str]
    missing_skills: list[str]


class Ranking(Strict):
    matches: list[Match]


class QuestionInput(Strict):
    question: str = Field(min_length=5, max_length=4000)
    followups: list[str] = Field(default_factory=list)
    candidate_answer: str = ''
    interviewer_notes: str = ''
    task: str = ''
    topic: str = Field(min_length=2, max_length=150)
    direction: Direction
    level: Level
    language: Language
    start: float = Field(default=0, ge=0)
    end: float = Field(default=0, ge=0)
    roles: str = ''
    needs_context: bool = True
    reference_answer: str = ''
    rubric: list[str] = Field(default_factory=list, max_length=20)
    material_ids: list[str] = Field(default_factory=list, max_length=20)


class ExtractedQuestions(Strict):
    questions: list[QuestionInput]


class SourceInput(Strict):
    url: str = Field(max_length=2000)
    direction: Direction = 'frontend'
    level: Level = 'junior'
    language: Language = 'ru'
    duration_seconds: int = Field(default=0, ge=0, le=10800)


class MaterialInput(Strict):
    url: str = Field(max_length=2000)
    direction: Direction
    level: Level
    language: Language


class InterviewInput(Strict):
    vacancy_id: str
    direction: Direction
    level: Level
    language: Language


class AnswerInput(Strict):
    text: str = Field(min_length=1, max_length=16000)
    confirmed: Literal[True]


class Evaluation(Strict):
    reliable: bool
    correctness: int | None = Field(ge=0, le=4)
    completeness: int | None = Field(ge=0, le=4)
    reasoning: int | None = Field(ge=0, le=4)
    feedback: str
    errors: list[str]
    missing_points: list[str]
    improved_answer: str


class HHQuery(Strict):
    text: str = Field(min_length=2, max_length=200)
    area: str | None = Field(default=None, pattern=r'^\d+$', max_length=20)
    regions: list[str] | None = Field(default=None, max_length=20)
    direction: Direction = 'frontend'
    level: Level = 'junior'
    work_format: Literal['remote', 'office', 'hybrid', 'any'] = 'any'
