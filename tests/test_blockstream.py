import pytest

from helpers.blockstream import Block, BlockStream


@pytest.mark.asyncio
async def test_block_emission_and_update_events():
    stream = BlockStream()

    await stream.emit("init", {"query": "hello"})
    block = await stream.emit_block("reasoning", {"text": "draft", "nested": {"x": 1}})
    update = await stream.update_block(
        block.id,
        [
            {"op": "replace", "path": "/data/text", "value": "final"},
            {"op": "replace", "path": "/data/nested/x", "value": 2},
        ],
    )

    assert isinstance(block, Block)
    assert block.data == {"text": "final", "nested": {"x": 2}}
    assert update["type"] == "updateBlock"
    assert update["blockId"] == block.id
    assert update["patch"] == [
        {"op": "replace", "path": "/data/text", "value": "final"},
        {"op": "replace", "path": "/data/nested/x", "value": 2},
    ]
    assert update["data"] == {"id": block.id, "ops": update["patch"]}
    assert stream.all_blocks() == [{"id": block.id, "type": "reasoning", "data": block.data}]
    assert [event["type"] for event in stream.events] == ["init", "block", "updateBlock"]
    block_event = stream.events[1]
    assert block_event["block"]["id"] == block.id
    assert block_event["data"]["block"]["id"] == block.id


@pytest.mark.asyncio
async def test_close_emits_done_once_and_queue_records_events():
    stream = BlockStream()

    await stream.emit_block("text", {"text": "answer"})
    await stream.close()
    await stream.close()

    assert [event["type"] for event in stream.events] == ["block", "done"]
    queued = [await stream.queue.get(), await stream.queue.get()]
    assert [event["type"] for event in queued] == ["block", "done"]


@pytest.mark.asyncio
async def test_rejects_unknown_event_and_block_types():
    stream = BlockStream()

    with pytest.raises(ValueError):
        await stream.emit("sources", {})
    with pytest.raises(ValueError):
        await stream.emit_block("unknown", {})


@pytest.mark.asyncio
async def test_upload_block_types_supported():
    stream = BlockStream()
    await stream.emit_block("upload_searching", {"queries": ["q1"]})
    await stream.emit_block("upload_search_results", {"files": [{"file_id": "f1"}]})
    assert [b.type for b in stream.blocks] == ["upload_searching", "upload_search_results"]
