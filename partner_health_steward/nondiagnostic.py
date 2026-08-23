"""Strict non-diagnostic candidate and approved claim contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .coordination import EvidenceCard, OwnerReplyAtom
from .initialization import stable_digest
from .knowledge import KnowledgeRelease


class NonDiagnosticContractViolation(ValueError):
    """A model candidate or approved atom crossed its allowed contract."""


ALLOWED_CLAIM_KINDS = frozenset({
    "owner-fact",
    "general-knowledge",
    "support",
    "opposition",
    "unknown",
    "limitation",
    "next-step",
})


def _mapping(value: object, fields: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise NonDiagnosticContractViolation(f"invalid {name}")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16384:
        raise NonDiagnosticContractViolation(f"invalid {name}")
    return value


def _texts(value: object, name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not list or (not value and not allow_empty):
        raise NonDiagnosticContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise NonDiagnosticContractViolation(f"invalid {name}")
    return result


@dataclass(frozen=True)
class CardReference:
    card_id: str
    version: str
    role: str

    def __post_init__(self) -> None:
        _text(self.card_id, "card identifier")
        _text(self.version, "card version")
        if self.role not in {"owner-fact", "general-knowledge"}:
            raise NonDiagnosticContractViolation("invalid card role")

    def to_wire(self) -> dict[str, object]:
        return {"card_id": self.card_id, "version": self.version, "role": self.role}

    @classmethod
    def from_wire(cls, value: object) -> "CardReference":
        fields = _mapping(value, frozenset({"card_id", "version", "role"}), "card reference")
        return cls(
            _text(fields["card_id"], "card identifier"),
            _text(fields["version"], "card version"),
            _text(fields["role"], "card role"),
        )


@dataclass(frozen=True)
class NonDiagnosticCandidate:
    owner_fact_refs: tuple[CardReference, ...]
    knowledge_refs: tuple[CardReference, ...]
    support: tuple[str, ...]
    opposition: tuple[str, ...]
    unknowns: tuple[str, ...]
    limitations: tuple[str, ...]
    next_steps: tuple[str, ...]
    claim_ids: tuple[str, ...]
    template_id: str

    def __post_init__(self) -> None:
        for refs, role, name in (
            (self.owner_fact_refs, "owner-fact", "owner fact references"),
            (self.knowledge_refs, "general-knowledge", "knowledge references"),
        ):
            if type(refs) is not tuple or any(type(item) is not CardReference or item.role != role for item in refs):
                raise NonDiagnosticContractViolation(f"invalid {name}")
        for values, name in (
            (self.support, "support statements"),
            (self.opposition, "opposition statements"),
            (self.unknowns, "unknown statements"),
            (self.limitations, "limitations"),
            (self.next_steps, "next steps"),
            (self.claim_ids, "claim identifiers"),
        ):
            if type(values) is not tuple or any(type(item) is not str or not item for item in values):
                raise NonDiagnosticContractViolation(f"invalid {name}")
        _text(self.template_id, "template identifier")

    def to_wire(self) -> dict[str, object]:
        return {
            "owner_fact_refs": [item.to_wire() for item in self.owner_fact_refs],
            "knowledge_refs": [item.to_wire() for item in self.knowledge_refs],
            "support": list(self.support),
            "opposition": list(self.opposition),
            "unknowns": list(self.unknowns),
            "limitations": list(self.limitations),
            "next_steps": list(self.next_steps),
            "claim_ids": list(self.claim_ids),
            "template_id": self.template_id,
        }

    @classmethod
    def from_wire(cls, value: object) -> "NonDiagnosticCandidate":
        fields = _mapping(value, frozenset({
            "owner_fact_refs", "knowledge_refs", "support", "opposition", "unknowns",
            "limitations", "next_steps", "claim_ids", "template_id",
        }), "non-diagnostic candidate")
        owner_refs = fields["owner_fact_refs"]
        knowledge_refs = fields["knowledge_refs"]
        if type(owner_refs) is not list or type(knowledge_refs) is not list:
            raise NonDiagnosticContractViolation("invalid candidate references")
        return cls(
            tuple(CardReference.from_wire(item) for item in owner_refs),
            tuple(CardReference.from_wire(item) for item in knowledge_refs),
            _texts(fields["support"], "support statements", allow_empty=True),
            _texts(fields["opposition"], "opposition statements", allow_empty=True),
            _texts(fields["unknowns"], "unknown statements", allow_empty=True),
            _texts(fields["limitations"], "limitations", allow_empty=True),
            _texts(fields["next_steps"], "next steps", allow_empty=True),
            _texts(fields["claim_ids"], "claim identifiers", allow_empty=True),
            _text(fields["template_id"], "template identifier"),
        )


@dataclass(frozen=True)
class ApprovedClaimAtom:
    atom_id: str
    kind: str
    text: str
    version: str

    def __post_init__(self) -> None:
        _text(self.atom_id, "claim atom identifier")
        if self.kind not in ALLOWED_CLAIM_KINDS:
            raise NonDiagnosticContractViolation("claim atom kind is not non-diagnostic")
        _text(self.text, "claim atom text")
        _text(self.version, "claim atom version")

    def to_wire(self) -> dict[str, object]:
        return {"atom_id": self.atom_id, "kind": self.kind, "text": self.text, "version": self.version}

    @classmethod
    def from_wire(cls, value: object) -> "ApprovedClaimAtom":
        fields = _mapping(value, frozenset({"atom_id", "kind", "text", "version"}), "approved claim atom")
        return cls(
            _text(fields["atom_id"], "claim atom identifier"),
            _text(fields["kind"], "claim atom kind"),
            _text(fields["text"], "claim atom text"),
            _text(fields["version"], "claim atom version"),
        )


@dataclass(frozen=True)
class ApprovedReplyTemplate:
    template_id: str
    version: str
    section_order: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.template_id, "reply template identifier")
        _text(self.version, "reply template version")
        if type(self.section_order) is not tuple or not self.section_order:
            raise NonDiagnosticContractViolation("invalid reply template section order")
        if any(section not in ALLOWED_CLAIM_KINDS for section in self.section_order):
            raise NonDiagnosticContractViolation("invalid reply template section order")
        if len(set(self.section_order)) != len(self.section_order):
            raise NonDiagnosticContractViolation("invalid reply template section order")

    def to_wire(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "section_order": list(self.section_order),
        }

    @classmethod
    def from_wire(cls, value: object) -> "ApprovedReplyTemplate":
        fields = _mapping(
            value,
            frozenset({"template_id", "version", "section_order"}),
            "approved reply template",
        )
        return cls(
            _text(fields["template_id"], "reply template identifier"),
            _text(fields["version"], "reply template version"),
            _texts(fields["section_order"], "reply template section order"),
        )


@dataclass(frozen=True)
class RenderedNonDiagnosticReply:
    text: str
    owner_fact_refs: tuple[CardReference, ...]
    knowledge_refs: tuple[CardReference, ...]
    reply_atoms: tuple[OwnerReplyAtom, ...] = ()

    def __post_init__(self) -> None:
        _text(self.text, "rendered non-diagnostic reply")

    def to_commit_wire(self) -> dict[str, object]:
        """Return only final approved reply facts; the model candidate is absent."""

        return {
            "owner_reply": self.text,
            "reply_atoms": [atom.to_storage() for atom in self.reply_atoms],
            "owner_fact_refs": [reference.to_wire() for reference in self.owner_fact_refs],
            "knowledge_refs": [reference.to_wire() for reference in self.knowledge_refs],
        }


class NonDiagnosticReplyPipeline:
    """Validate current authorities and render without retaining model candidates."""

    def __init__(
        self,
        *,
        current_owner_cards: tuple[EvidenceCard, ...],
        current_knowledge_releases: tuple[KnowledgeRelease, ...],
        approved_claims: tuple[ApprovedClaimAtom, ...],
        approved_templates: tuple[ApprovedReplyTemplate, ...],
    ) -> None:
        if any(type(card) is not EvidenceCard for card in current_owner_cards):
            raise NonDiagnosticContractViolation("invalid current owner cards")
        if any(type(release) is not KnowledgeRelease for release in current_knowledge_releases):
            raise NonDiagnosticContractViolation("invalid current knowledge releases")
        if any(type(claim) is not ApprovedClaimAtom for claim in approved_claims):
            raise NonDiagnosticContractViolation("invalid approved claims")
        if any(type(template) is not ApprovedReplyTemplate for template in approved_templates):
            raise NonDiagnosticContractViolation("invalid approved templates")
        self._owner_cards = {card.evidence_id: card for card in current_owner_cards}
        self._knowledge_releases = {
            release.release_id: release for release in current_knowledge_releases
        }
        self._approved_claims = {claim.atom_id: claim for claim in approved_claims}
        self._approved_templates = {
            template.template_id: template for template in approved_templates
        }
        self._knowledge_release_values = current_knowledge_releases
        self._approved_claim_values = approved_claims
        self._approved_template_values = approved_templates

    def with_current_owner_cards(
        self,
        current_owner_cards: tuple[EvidenceCard, ...],
    ) -> "NonDiagnosticReplyPipeline":
        """Rebind only owner facts while retaining the immutable governed policy."""

        return NonDiagnosticReplyPipeline(
            current_owner_cards=current_owner_cards,
            current_knowledge_releases=self._knowledge_release_values,
            approved_claims=self._approved_claim_values,
            approved_templates=self._approved_template_values,
        )

    def approved_template(self, template_id: str) -> ApprovedReplyTemplate:
        try:
            return self._approved_templates[template_id]
        except KeyError as exc:
            raise NonDiagnosticContractViolation(
                "candidate template is not approved"
            ) from exc

    def render(self, candidate: NonDiagnosticCandidate) -> RenderedNonDiagnosticReply:
        if type(candidate) is not NonDiagnosticCandidate:
            raise NonDiagnosticContractViolation("invalid non-diagnostic candidate")
        if not candidate.support:
            raise NonDiagnosticContractViolation("support section is required")
        if not candidate.opposition:
            raise NonDiagnosticContractViolation("opposition section is required")
        if not candidate.unknowns:
            raise NonDiagnosticContractViolation("unknown section is required")
        if not candidate.limitations:
            raise NonDiagnosticContractViolation("limitation section is required")
        if not candidate.next_steps:
            raise NonDiagnosticContractViolation("next-step section is required")
        if any(claim_id not in self._approved_claims for claim_id in candidate.claim_ids):
            raise NonDiagnosticContractViolation("candidate claim is not approved")
        if candidate.template_id not in self._approved_templates:
            raise NonDiagnosticContractViolation("candidate template is not approved")
        for reference in candidate.owner_fact_refs:
            card = self._owner_cards.get(reference.card_id)
            if card is None or card.card_version != reference.version or card.evidence_type != "personal-health":
                raise NonDiagnosticContractViolation("owner fact reference is not current")
        for reference in candidate.knowledge_refs:
            release = self._knowledge_releases.get(reference.card_id)
            if release is None or release.release_version != reference.version:
                raise NonDiagnosticContractViolation("knowledge reference is not current")

        template = self._approved_templates[candidate.template_id]
        section_claims: dict[str, tuple[str, ...]] = {
            "owner-fact": tuple(
                claim_id
                for claim_id in candidate.claim_ids
                if self._approved_claims[claim_id].kind == "owner-fact"
            ),
            "general-knowledge": tuple(
                claim_id
                for claim_id in candidate.claim_ids
                if self._approved_claims[claim_id].kind == "general-knowledge"
            ),
            "support": candidate.support,
            "opposition": candidate.opposition,
            "unknown": candidate.unknowns,
            "limitation": candidate.limitations,
            "next-step": candidate.next_steps,
        }
        if candidate.owner_fact_refs and not section_claims["owner-fact"]:
            raise NonDiagnosticContractViolation("owner facts lack an approved claim")
        if candidate.knowledge_refs and not section_claims["general-knowledge"]:
            raise NonDiagnosticContractViolation("knowledge references lack an approved claim")
        for section, claim_ids in section_claims.items():
            for claim_id in claim_ids:
                claim = self._approved_claims.get(claim_id)
                if (
                    claim is None
                    or claim_id not in candidate.claim_ids
                    or claim.kind != section
                ):
                    raise NonDiagnosticContractViolation("claim section kind mismatch")
        ordered_claim_ids = tuple(
            claim_id
            for section in template.section_order
            for claim_id in section_claims.get(section, ())
        )
        if len(set(candidate.claim_ids)) != len(candidate.claim_ids) or set(ordered_claim_ids) != set(candidate.claim_ids):
            raise NonDiagnosticContractViolation("candidate claims do not match the approved template")

        owner_refs = ", ".join(
            f"{reference.card_id}@{reference.version}"
            for reference in candidate.owner_fact_refs
        )
        knowledge_refs = ", ".join(
            f"{reference.card_id}@{reference.version}"
            for reference in candidate.knowledge_refs
        )
        candidate_digest = stable_digest(candidate.to_wire())
        reply_atoms: list[OwnerReplyAtom] = []
        for section in template.section_order:
            for claim_id in section_claims[section]:
                claim = self._approved_claims[claim_id]
                text = claim.text
                if section == "owner-fact":
                    text = f"{text} 依据：{owner_refs}"
                elif section == "general-knowledge":
                    text = f"{text} 依据：{knowledge_refs}"
                atom_kind = (
                    "limitation"
                    if section == "limitation"
                    else "next-step"
                    if section == "next-step"
                    else "direct-result"
                )
                reply_atoms.append(
                    OwnerReplyAtom.form(
                        kind=atom_kind,
                        text=text,
                        # The core separately revalidates every typed reference
                        # and approved atom.  The generic daily-turn ledger sees
                        # only the steward's final, reference-free selection; it
                        # must not invent a ResponsibilityResult for the model.
                        source_skill="health-steward",
                        source_result_digest=candidate_digest,
                    )
                )
        return RenderedNonDiagnosticReply(
            text="\n".join(atom.text for atom in reply_atoms),
            owner_fact_refs=candidate.owner_fact_refs,
            knowledge_refs=candidate.knowledge_refs,
            reply_atoms=tuple(reply_atoms),
        )
