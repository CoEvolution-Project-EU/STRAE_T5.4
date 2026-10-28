from unittest.mock import AsyncMock

import pytest
from app.models.requests import GenerationMetadata
from app.services.generator import (
    GeneratorGenerationError,
    GeneratorMissingReportError,
    GeneratorSigningError,
    GeneratorStorageError,
)
from app.worker import consume_messages

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    get_generation_metadata,
    get_generation_metadata_deprecation,
    get_generation_metadata_deprecation_with_gadgets,
)


class FakeMessage:
    def __init__(self, value):
        self.value = value


class FakeConsumer:
    """Minimal stand-in for `AIOKafkaConsumer` driving `consume_messages`."""

    def __init__(self, values):
        self._messages = [FakeMessage(v) for v in values]
        self.commit_calls = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def commit(self):
        self.commit_calls += 1


def make_generator(side_effect=None, return_value=None):
    generator = AsyncMock()
    if side_effect is not None:
        generator.generate.side_effect = side_effect
    else:
        generator.generate.return_value = return_value or AsyncMock(
            serial_number="urn:uuid:test"
        )
    return generator


def base_event(**overrides):
    event = {"model_uuid": MODEL_UUID, "version": MODEL_VERSION}
    event.update(overrides)
    return event


# ============ Malformed payloads: must be committed (poison-message safe) and never reach the generator ============


@pytest.mark.anyio
async def test_missing_required_fields_is_committed_and_skipped():
    consumer = FakeConsumer([{"model_uuid": MODEL_UUID}])  # missing "version"
    generator = make_generator()

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_non_dict_payload_is_committed_and_skipped():
    consumer = FakeConsumer(["not-an-object", ["also", "not"], None])
    generator = make_generator()

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 3
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_new_event_missing_reports_is_committed_and_skipped():
    # No "event" key and no "reports" key: previously this raised an
    # uncaught KeyError that skipped the commit, wedging the partition.
    consumer = FakeConsumer([base_event()])
    generator = make_generator()

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_new_event_reports_wrong_type_is_committed_and_skipped():
    consumer = FakeConsumer([base_event(reports="not-an-object")])
    generator = make_generator()

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_updated_event_missing_changed_reports_is_committed_and_skipped():
    consumer = FakeConsumer(
        [base_event(event="updated-aimbom-requested")]  # no "changedReports"
    )
    generator = make_generator()

    await consume_messages(consumer, generator)

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

    await consume_messages(consumer, generator)

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

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


@pytest.mark.anyio
async def test_reports_failing_schema_validation_is_committed_and_skipped():
    # "reports" is an object but has a value that cannot be parsed as a
    # ReportDetails entry, so GenerationMetadata(...) construction fails.
    consumer = FakeConsumer([base_event(reports={"risk_report": "not-a-report"})])
    generator = make_generator()

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_not_called()


# ============ Well-formed payloads: reach the generator with the expected GenerationMetadata ============


@pytest.mark.anyio
async def test_valid_new_event_calls_generator_and_commits():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator()

    await consume_messages(consumer, generator)

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

    await consume_messages(consumer, generator)

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

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 1
    generator.generate.assert_awaited_once_with(
        GenerationMetadata(**metadata),
    )


# ============ Generation failures: existing commit/no-commit semantics must be preserved ============


@pytest.mark.anyio
async def test_missing_report_error_is_committed():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(side_effect=GeneratorMissingReportError("missing"))

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 1


@pytest.mark.anyio
async def test_storage_error_is_not_committed():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(side_effect=GeneratorStorageError("storage down"))

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 0


@pytest.mark.anyio
async def test_signing_error_is_not_committed():
    # A signing key/certificate mismatch reflects the environment, not the
    # message, and is typically transient (e.g. caught mid-rotation) -- it
    # must be retried, not treated as a poison message.
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(
        side_effect=GeneratorSigningError("signing key and certificate do not match")
    )

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 0


@pytest.mark.anyio
async def test_generation_error_is_committed():
    metadata = get_generation_metadata(MODEL_UUID, MODEL_VERSION)
    consumer = FakeConsumer([base_event(reports=metadata["reports"])])
    generator = make_generator(side_effect=GeneratorGenerationError("bad report"))

    await consume_messages(consumer, generator)

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

    await consume_messages(consumer, generator)

    assert consumer.commit_calls == 2
    generator.generate.assert_awaited_once()
