"""Pure, typed two-stage daily runtime; network and credentials stay in Plugin."""
from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .authority import AuthorityValidationError
from .admission import SourceEnvelope
from .coordination import (
    AtomicEvidenceClaim, DailyHealthState, DailySkillAttestor, DailySkillBundle,
    DailySkillRuntime, EvidenceDecision, EvidenceSeriesKey, PersonalHealthFields,
    PortraitDecision, PortraitProofLink, StewardPlan, StewardResolution,
    StewardContext, StewardResolutionContext, SettingsDecision, OwnerInquiryDecision,
    LiteratureDecision, RECORDING_EXCLUDED_TEMPORARY_PURPOSE,
)
from .evidence_profile import PersonalEvidenceProfile
from .model_contract import ModelMessage, NonDiagnosticOperationalBudget, StrictHealthLLM
from .model_adapter import (
    NonDiagnosticBudgetInputMeasurementStrategy, NONDIAGNOSTIC_INTAKE_SCHEMA_NAME,
    NONDIAGNOSTIC_INTAKE_SCHEMA_DIGEST, NONDIAGNOSTIC_OPERATION_SCHEMA_NAME,
    NONDIAGNOSTIC_OPERATION_SCHEMA_DIGEST,
)
from .portrait_schema import PORTRAIT_TOPIC_REFS


def _span(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise AuthorityValidationError("invalid intake span")
    if type(value['start']) is not int or type(value['end']) is not int or not 0 <= value['start'] < value['end']:
        raise AuthorityValidationError("invalid intake offsets")
    if type(value['quote']) is not str or not value['quote'] or len(value['quote'].encode()) > 16384:
        raise AuthorityValidationError("invalid intake quote")
    return tuple((key, value[key]) for key in sorted(fields))


@dataclass(frozen=True)
class NonDiagnosticIntakeCandidate:
    operation: str
    facts: tuple[tuple[tuple[str, object], ...], ...]
    question: tuple[tuple[str, object], ...] | None

    def __post_init__(self):
        if self.operation not in {'record', 'question', 'mixed', 'clarify'} or type(self.facts) is not tuple or len(self.facts) > 8:
            raise AuthorityValidationError("invalid intake operation")
        if self.operation == 'record' and (not self.facts or self.question is not None):
            raise AuthorityValidationError("invalid record intake")
        if self.operation == 'question' and (self.facts or self.question is None):
            raise AuthorityValidationError("invalid question intake")
        if self.operation == 'mixed' and (not self.facts or self.question is None):
            raise AuthorityValidationError("invalid mixed intake")
        if self.operation == 'clarify' and self.facts:
            raise AuthorityValidationError("clarify cannot contain facts")

    @classmethod
    def from_wire(cls, value):
        if type(value) is not dict or set(value) != {'operation', 'facts', 'question'} or type(value['facts']) is not list:
            raise AuthorityValidationError("invalid intake candidate")
        facts = []
        for item in value['facts']:
            fields = {'start', 'end', 'quote', 'topic_ref', 'time_start', 'time_end'}
            fact = _span(item, fields)
            if item['topic_ref'] is not None and item['topic_ref'] not in PORTRAIT_TOPIC_REFS:
                raise AuthorityValidationError("invalid intake topic")
            a, b = item['time_start'], item['time_end']
            if (a is None) != (b is None) or a is not None and (type(a) is not int or type(b) is not int or not item['start'] <= a < b <= item['end']):
                raise AuthorityValidationError("invalid intake time offsets")
            facts.append(fact)
        query = None if value['question'] is None else _span(value['question'], {'start', 'end', 'quote'})
        return cls(value['operation'], tuple(facts), query)

    def to_wire(self):
        return {'operation': self.operation, 'facts': [dict(item) for item in self.facts],
                'question': None if self.question is None else dict(self.question)}

    def validate_source(self, body):
        if type(body) is not str or not body:
            raise AuthorityValidationError("intake source unavailable")
        spans = [dict(item) for item in self.facts]
        if self.question is not None:
            spans.append(dict(self.question))
        covered = []
        clauses = []
        for match in re.finditer(r'[^，,；;。！？!?\n]+[！？?]?', body):
            a, b = match.span()
            while a < b and body[a].isspace(): a += 1
            while b > a and body[b-1].isspace(): b -= 1
            if a < b: clauses.append((a,b))
        for item in spans:
            a,b = item['start'],item['end']
            if b > len(body) or body[a:b] != item['quote'] or any(a < d and c < b for c,d in covered):
                raise AuthorityValidationError("intake source quote mismatch")
            covered.append((a,b))
        for item in map(dict, self.facts):
            quote = item['quote']
            if (item['start'],item['end']) not in clauses:
                raise AuthorityValidationError("intake fact omitted a clause qualifier")
            if re.search(r'[?？]|是不是|是否|会不会|有没有|怎么|怎样|如何|假如|如果|假设|请.*(?:诊断|判断)|帮我.*(?:诊断|判断)', quote):
                raise AuthorityValidationError("intake question is not an owner fact")
        return self


class GovernedNonDiagnosticRuntime:
    """Own only typed pure Skill execution; accept no production callbacks."""
    def __init__(self, intake_llm, answer_llm, measurement_strategy, *, bundle, attestor, clock=None):
        if type(intake_llm) is not StrictHealthLLM or type(answer_llm) is not StrictHealthLLM or type(measurement_strategy) is not NonDiagnosticBudgetInputMeasurementStrategy:
            raise AuthorityValidationError("invalid governed model dependencies")
        self.intake_llm = StrictHealthLLM.canonical_copy(intake_llm)
        self.answer_llm = StrictHealthLLM.canonical_copy(answer_llm)
        self.measurement_strategy = NonDiagnosticBudgetInputMeasurementStrategy.canonical_copy(measurement_strategy)
        self.budget = object.__getattribute__(self.measurement_strategy, '_profile')
        if type(self.budget) is not NonDiagnosticOperationalBudget or type(bundle) is not DailySkillBundle or type(attestor) is not DailySkillAttestor:
            raise AuthorityValidationError("invalid governed runtime resources")
        for llm, name, digest in ((self.intake_llm, NONDIAGNOSTIC_INTAKE_SCHEMA_NAME, NONDIAGNOSTIC_INTAKE_SCHEMA_DIGEST),
                                  (self.answer_llm, NONDIAGNOSTIC_OPERATION_SCHEMA_NAME, NONDIAGNOSTIC_OPERATION_SCHEMA_DIGEST)):
            if (object.__getattribute__(llm, '_route') != self.budget.route or object.__getattribute__(llm, '_capability_profile') != self.budget
                    or object.__getattribute__(llm, '_strict_schema_name') != name or object.__getattribute__(llm, '_strict_schema_digest') != digest
                    or type(object.__getattribute__(llm, '_measurement_strategy')) is not NonDiagnosticBudgetInputMeasurementStrategy):
                raise AuthorityValidationError("governed stage authority mismatch")
        if clock is not None and not callable(clock):
            raise AuthorityValidationError("invalid governed clock")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._formation = ContextVar('governed-intake-formation', default=None)
        self._daily_runtime = DailySkillRuntime(bundle, attestor, executor=self._execute, clock=self._clock)

    @property
    def daily_runtime(self): return self._daily_runtime

    def core_dependencies(self): return {'governed_nondiagnostic_runtime': self}

    @property
    def model_use_disclosure(self): return self.budget.model_use_disclosure

    def llm(self, stage):
        if stage not in {'intake','answer'}: raise AuthorityValidationError("invalid governed stage")
        return self.intake_llm if stage == 'intake' else self.answer_llm

    def request(self, source, stage, *, owner_cards=(), claims=(), templates=()):
        if type(source) is not SourceEnvelope or source.body is None:
            raise AuthorityValidationError("governed source body unavailable")
        if stage == 'intake':
            policy = ('从主人原文中抽取完整陈述分句及问题。只返回固定intake JSON。保留否定、条件、时间；疑问、假设和诊断请求不是事实。'
                      'offset使用Python Unicode索引。事实最多8条，不改写、不猜时间、诊断或可靠性。topic_ref只可为给定枚举或null。')
        else:
            import json
            policy = ('只返回固定非诊断候选。只用以下当前Core批准引用和文案，不生成自由回答、诊断或任务批准。'
                      + json.dumps({'owner_cards':[c.to_storage() for c in owner_cards],
                                    'claims':[c.to_wire() for c in claims], 'templates':[t.to_wire() for t in templates]}, ensure_ascii=False))
        return self.measurement_strategy.prepare_request((ModelMessage('system',policy), ModelMessage('user',source.body)), stage=stage)

    def evidence_stage(self, source, state, candidate, owner_timezone, *, recording_stopped=False):
        candidate = NonDiagnosticIntakeCandidate.from_wire(candidate.to_wire()).validate_source(source.body)
        token = self._formation.set((source, candidate, owner_timezone, recording_stopped))
        try: return self._daily_runtime.execute_evidence_stage(source,state)
        finally: self._formation.reset(token)

    def _claim(self, source, fact, zone):
        quote = fact['quote']; occurred = 'unknown'; certainty = 'uncertain'
        if fact['time_start'] is not None:
            text = source.body[fact['time_start']:fact['time_end']]
            try:
                stamp = datetime.fromisoformat(source.protocol_timestamp).astimezone(ZoneInfo(zone))
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
                    occurred = datetime.fromisoformat(text).date().isoformat()
                elif text in {'今天','今早','今晚'}: occurred = stamp.date().isoformat()
                elif text in {'昨天','昨晚'}: occurred = (stamp.date()-timedelta(days=1)).isoformat()
                if occurred != 'unknown': certainty = 'known'
            except (ValueError, TypeError, KeyError): pass
        topics = () if fact['topic_ref'] is None else (fact['topic_ref'],)
        return AtomicEvidenceClaim(quote,'personal-health','owner-statement',occurred,occurred,
            'non-diagnostic-health','主人陈述，尚未独立核实',('不推断未说明的次数、原因、可靠性或趋势',),
            (quote,),('诊断','测量验证'),topics,PersonalHealthFields('owner-statement'),
            EvidenceSeriesKey('personal-health',fact['topic_ref'] or 'owner-statement',PersonalEvidenceProfile('owner-statement'),'owner-stated-period'),certainty)

    def _execute(self, name, context):
        if name == 'health-steward' and type(context) is StewardContext:
            formation = self._formation.get()
            if formation is None or formation[0].causal_id != context.source_causal_id:
                raise AuthorityValidationError("verified intake formation required")
            source,candidate,zone,stopped = formation
            if stopped:
                return StewardPlan(RECORDING_EXCLUDED_TEMPORARY_PURPOSE, ('health-owner-inquiry',),(), inquiry_gap='owner-requested temporary clarification')
            claims = tuple(self._claim(source,dict(f),zone) for f in candidate.facts)
            skills = []
            if claims: skills.append('health-evidence')
            if any(c.topic_refs for c in claims): skills.append('health-portrait')
            if not claims: skills.append('health-owner-inquiry')
            return StewardPlan('non-diagnostic-health',tuple(skills),claims,
                inquiry_gap='请明确你希望记录的完整陈述或具体问题' if not claims else None)
        if name == 'health-steward' and type(context) is StewardResolutionContext:
            return StewardResolution(context.candidate_evidence_ids,context.candidate_portrait_topic_refs,
                tuple(a.atom_id for a in context.reply_atoms),context.candidate_evidence_change_ids)
        if name == 'health-evidence': return EvidenceDecision.admit(context.atomic_claim)
        if name == 'health-portrait':
            topic = context.affected_topic_refs[0]
            cards = tuple(c for c in context.committed_related_cards if topic in c.topic_refs)
            if not cards or len(cards) > 3 or any(len('主人原文：'+c.content)>60 for c in cards):
                return PortraitDecision.gap('主人原文无法在当前完整展示边界内表达')
            items=tuple('主人原文：'+c.content for c in cards)
            links=tuple(PortraitProofLink(c.evidence_id,'supports',topic,'current-understanding',text,applicable_period=c.applicable_period) for c,text in zip(cards,items))
            return PortraitDecision('update',topic,items,proof_links=links)
        if name == 'health-owner-inquiry': return OwnerInquiryDecision.gap('required-context-unavailable')
        if name == 'health-settings': return SettingsDecision.no_change()
        if name == 'health-literature': return LiteratureDecision.no_qualified_material('无当前批准知识')
        raise AuthorityValidationError("unsupported governed Skill context")
