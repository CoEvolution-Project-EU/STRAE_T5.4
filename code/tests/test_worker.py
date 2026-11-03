from functools import partial
from unittest.mock import AsyncMock

import pytest
from app.core.config import settings
from app.models.requests import GenerationMetadata, SigningMetadata
from app.services.generator import (
    GeneratorGenerationError,
    GeneratorMissingReportError,
    GeneratorSigningError,
    GeneratorStorageError,
)
from app.services.report_signer import (
    ReportSignerInvalidFileError,
    ReportSignerMissingReportError,
    ReportSignerProcessingError,
    ReportSignerSigningError,
    ReportSignerStorageError,
    ReportSignerUploadRejectedError,
    SigningResult,
)
from aiokafka import TopicPartition
from app.consumers.generation import handle_generation_event
from app.consumers.signing import handle_signing_event
from app.worker import _deserialize, consume_messages

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    get_generation_metadata,
    get_generation_metadata_deprecation,
    get_generation_metadata_deprecation_with_gadgets,
    get_signing_event,
)


class FakeMessage:
    def __init__(self, value, topic, partition, offset):
        self.value = value
        self.topic = topic
        self.partition = partition
        self.offset = offset


class FakeConsumer:
    """Minimal stand-in for `AIOKafkaConsumer` driving `consume_messages`.

    Messages are delivered once, in order, from partition 0.
    """

    def __init__(self, values, topic=settings.KAFKA_TOPIC):
        self._messages = [
            FakeMessage(value, topic, partition=0, offset=offset)
            for offset, value in enumerate(values)
        ]
        self.commits = []

    @property
    def commit_calls(self):
        return len(self.commits)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def commit(self, offsets):
        self.commits.append(offsets)



async def run_generation(consumer, generator):
    await consume_messages(
        consumer, partial(handle_generation_event, generator=generator)
    )


async def run_signing(consumer, signer):
    await consume_messages(consumer, partial(handle_signing_event, signer=signer))


def make_generator(side_effect=None, return_value=None):
    generator = AsyncMock()
    if side_effect is not None:
        generator.generate.side_effect = side_effect
    else:
        generator.generate.return_value = return_value or AsyncMock(
            serial_number="urn:uuid:test"
        )
    return generator


def make_signer(side_effect=None):
    signer = AsyncMock()
    signer.sign_and_upload.side_effect = side_effect
    signer.sign_and_upload.return_value = SigningResult(signed=1)
    return signer


def base_event(**overrides):
    event = {"model_uuid": MODEL_UUID, "version": MODEL_VERSION}
    event.update(overrides)
    return event


# ============ Malformed payloads: must be committed (poison-message safe) and never reach the generator ============


@pytest.mark.anyio
async def test_missing_required_fields_is_committed_and_skipped():
    consumer = FakeConsumer([{"model_uuid": MODEL_UUID}])  # missing "version"
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_non_dict_payload_is_committed_and_skipped():
    consumer = FakeConsumer(["not-an-object", ["also", "not"], None])
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 3
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_new_event_missing_reports_is_committed_and_skipped():
    # No "event" key and no "reports" key: previously this raised an
    # uncaught KeyError that skipped the commit, wedging the partition.
    consumer = FakeConsumer([base_event()])
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_new_event_reports_wrong_type_is_committed_and_skipped():
    consumer = FakeConsumer([base_event(reports="not-an-object")])
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_updated_event_missing_changed_reports_is_committed_and_skipped():
    consumer = FakeConsumer(
        [base_event(event="updated-aimbom-requested")]  # no "changedReports"
    )
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_updated_event_missing_aimbom_report_is_committed_and_skipped():
    consumer = FakeConsumer(
        [
            base_event(
                event="updated-aimbom-requested",
                changedReports={
                    "assessment_report": {"download_url": "reports/x/1.0/a.json"}
                },
            )
        ]
    )
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_updated_event_missing_risk_report_is_committed_and_skipped():
    consumer = FakeConsumer(
        [
            base_event(
                event="updated-aimbom-requested",
                changedReports={
                    "aimbom_report": {"download_url": "aimboms/x/1.0/aimbom.json"},
                    "assessment_report": {"download_url": "reports/x/1.0/a.json"},
                    # no "risk_report"
                },
            )
        ]
    )
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_reports_failing_schema_validation_is_committed_and_skipped():
    # "reports" is an object but has a value that cannot be parsed as a
    # ReportDetails entry, so GenerationMetadata(...) construction fails.
    consumer = FakeConsumer([base_event(reports={"risk_report": "not-a-report"})])
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


# ============ Well-formed payloads: reach the generator with the expected GenerationMetadata ============


@pytest.mark.anyio
async def test_valid_new_event_calls_generator_and_commits():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_awaited_once_with(
        GenerationMetadata(**metadata),
    )


@pytest.mark.anyio
async def test_valid_updated_event_calls_generator_and_commits():
    metadata = get_generation_metadata_deprecation(MODEL_UUID, MODEL_VERSION)
    changed_reports = dict(metadata["reports"])
    changed_reports["aimbom_report"] = metadata["previous_aimbom"]

    consumer = FakeConsumer(
        [
            base_event(
                event="updated-aimbom-requested",
                changedReports=changed_reports,
            )
        ]
    )
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_awaited_once_with(
        GenerationMetadata(**metadata),
    )


@pytest.mark.anyio
async def test_valid_updated_event_with_gadgets_report_calls_generator_and_commits():
    metadata = get_generation_metadata_deprecation_with_gadgets(
        MODEL_UUID, MODEL_VERSION
    )
    changed_reports = dict(metadata["reports"])
    changed_reports["aimbom_report"] = metadata["previous_aimbom"]

    consumer = FakeConsumer(
        [
            base_event(
                event="updated-aimbom-requested",
                changedReports=changed_reports,
            )
        ]
    )
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_awaited_once_with(
        GenerationMetadata(**metadata),
    )


# ============ Generation failures: committed and not retried, so they never block the queue ============


@pytest.mark.anyio
async def test_missing_report_error_is_committed():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(side_effect=GeneratorMissingReportError("missing"))

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1


@pytest.mark.anyio
async def test_storage_error_is_committed():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(side_effect=GeneratorStorageError("storage down"))

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1


@pytest.mark.anyio
async def test_signing_error_is_committed():
    # Not retried, so the queue isn't blocked while the signing material is
    # inconsistent.
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(
        side_effect=GeneratorSigningError("signing key and certificate do not match")
    )

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1


@pytest.mark.anyio
async def test_generation_error_is_committed():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(side_effect=GeneratorGenerationError("bad report"))

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1


@pytest.mark.anyio
async def test_bad_message_does_not_block_subsequent_valid_message():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer(
        [
            base_event(),  # malformed: no "reports"
            base_event(reports=metadata["reports"]),  # valid
        ]
    )
    generator = make_generator()

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 2
    generator.generate.assert_awaited_once()


# ============ Commits: every message is committed, only on its own partition ============


@pytest.mark.anyio
async def test_commit_only_covers_the_message_partition():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer(
        [base_event(), base_event(reports=metadata["reports"])]  # offsets 0 and 1
    )

    await run_generation(consumer, make_generator())

    partition = TopicPartition(settings.KAFKA_TOPIC, 0)
    assert consumer.commits == [{partition: 1}, {partition: 2}]


@pytest.mark.anyio
async def test_failed_message_does_not_block_subsequent_message():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer(
        [base_event(reports=metadata["reports"]), base_event(reports=metadata["reports"])]
    )
    generator = make_generator()
    generator.generate.side_effect = [
        GeneratorStorageError("storage down"),
        AsyncMock(serial_number="urn:uuid:test"),
    ]

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 2
    assert generator.generate.await_count == 2


@pytest.mark.anyio
async def test_unexpected_error_is_committed():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(side_effect=RuntimeError("unexpected"))

    await run_generation(consumer, generator)

    assert consumer.commit_calls == 1


def test_invalid_json_is_deserialized_as_none():
    assert _deserialize(b"not json") is None
    assert _deserialize(b"\xff\xfe") is None
    assert _deserialize(b'{"model_uuid": "x"}') == {"model_uuid": "x"}


# ============ Signing consumer: events are signed with the expected SigningMetadata ============


@pytest.mark.anyio
async def test_signing_event_calls_signer_and_commits():
    event = get_signing_event("reports/a.json", "reports/b.json")
    consumer = FakeConsumer([event], topic=settings.KAFKA_SIGNING_TOPIC)
    signer = make_signer()

    await run_signing(consumer, signer)

    assert consumer.commits == [{TopicPartition(settings.KAFKA_SIGNING_TOPIC, 0): 1}]
    signer.sign_and_upload.assert_awaited_once_with(
        SigningMetadata.model_validate(event)
    )


@pytest.mark.anyio
async def test_signing_event_logs_signed_counts(caplog):
    consumer = FakeConsumer(
        [get_signing_event("reports/a.json", "reports/b.json")],
        topic=settings.KAFKA_SIGNING_TOPIC,
    )
    signer = make_signer()
    signer.sign_and_upload.return_value = SigningResult(signed=1, already_signed=1)

    with caplog.at_level("INFO", logger="app.consumers.signing"):
        await run_signing(consumer, signer)

    assert "signed=1, already_signed=1" in caplog.text


@pytest.mark.anyio
async def test_generation_event_on_signing_consumer_is_committed_and_skipped():
    # A generation request is never signed, nor passed on to the generator.
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer(
        [base_event(reports=metadata["reports"])],
        topic=settings.KAFKA_SIGNING_TOPIC,
    )
    signer = make_signer()

    await run_signing(consumer, signer)

    assert consumer.commit_calls == 1
    signer.sign_and_upload.assert_not_called()


@pytest.mark.anyio
async def test_invalid_signing_event_is_committed_and_skipped():
    event = get_signing_event("reports/a.json")
    del event["target_bucket"]
    consumer = FakeConsumer([event], topic=settings.KAFKA_SIGNING_TOPIC)
    signer = make_signer()

    await run_signing(consumer, signer)

    assert consumer.commit_calls == 1
    signer.sign_and_upload.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        ReportSignerMissingReportError("missing"),
        ReportSignerInvalidFileError("invalid"),
        ReportSignerUploadRejectedError("rejected"),
        ReportSignerProcessingError("failed"),
        ReportSignerStorageError("storage down"),
        ReportSignerSigningError("signing key and certificate do not match"),
        RuntimeError("unexpected"),
    ],
)
@pytest.mark.anyio
async def test_signing_error_is_committed(error):
    consumer = FakeConsumer(
        [get_signing_event("reports/a.json")], topic=settings.KAFKA_SIGNING_TOPIC
    )
    signer = make_signer(side_effect=error)

    await run_signing(consumer, signer)

    assert consumer.commit_calls == 1

