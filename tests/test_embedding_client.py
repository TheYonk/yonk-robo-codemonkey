"""Tests for embedding clients with mocked HTTP responses."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from yonk_code_robomonkey.embeddings.ollama import ollama_embed
from yonk_code_robomonkey.embeddings.vllm_openai import vllm_embed


@pytest.mark.asyncio
async def test_ollama_embed_single_text():
    """Test Ollama embedding with a single text."""
    mock_response = MagicMock()  # Use MagicMock for response object
    mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        embeddings = await ollama_embed(
            texts=["hello world"],
            model="test-model",
            base_url="http://localhost:11434"
        )

    assert len(embeddings) == 1
    assert embeddings[0] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_ollama_embed_multiple_texts():
    """Test Ollama embedding with multiple texts."""
    mock_response1 = MagicMock()
    mock_response1.json.return_value = {"embedding": [0.1, 0.2]}
    mock_response1.raise_for_status = MagicMock()

    mock_response2 = MagicMock()
    mock_response2.json.return_value = {"embedding": [0.3, 0.4]}
    mock_response2.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.side_effect = [mock_response1, mock_response2]

    with patch("httpx.AsyncClient", return_value=mock_client):
        embeddings = await ollama_embed(
            texts=["text1", "text2"],
            model="test-model",
            base_url="http://localhost:11434"
        )

    assert len(embeddings) == 2
    assert embeddings[0] == [0.1, 0.2]
    assert embeddings[1] == [0.3, 0.4]


@pytest.mark.asyncio
async def test_ollama_embed_empty_list():
    """Test Ollama embedding with empty list."""
    embeddings = await ollama_embed(
        texts=[],
        model="test-model",
        base_url="http://localhost:11434"
    )
    assert embeddings == []


@pytest.mark.asyncio
async def test_vllm_embed_single_text():
    """Test vLLM embedding with a single text."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.5, 0.6, 0.7]}
        ]
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        embeddings = await vllm_embed(
            texts=["hello world"],
            model="test-model",
            base_url="http://localhost:8000",
            api_key="test-key"
        )

    assert len(embeddings) == 1
    assert embeddings[0] == [0.5, 0.6, 0.7]


@pytest.mark.asyncio
async def test_vllm_embed_batch():
    """Test vLLM embedding with batch of texts."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
            {"embedding": [0.5, 0.6]}
        ]
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        embeddings = await vllm_embed(
            texts=["text1", "text2", "text3"],
            model="test-model",
            base_url="http://localhost:8000",
            api_key="test-key",
            batch_size=10
        )

    assert len(embeddings) == 3
    assert embeddings[0] == [0.1, 0.2]
    assert embeddings[1] == [0.3, 0.4]
    assert embeddings[2] == [0.5, 0.6]


@pytest.mark.asyncio
async def test_vllm_embed_empty_list():
    """Test vLLM embedding with empty list."""
    embeddings = await vllm_embed(
        texts=[],
        model="test-model",
        base_url="http://localhost:8000",
        api_key="test-key"
    )
    assert embeddings == []


@pytest.mark.asyncio
async def test_ollama_embed_http_error():
    """Test Ollama embedding handles HTTP errors."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Server Error",
        request=MagicMock(),
        response=MagicMock()
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Ollama embedding failed"):
            await ollama_embed(
                texts=["test"],
                model="test-model",
                base_url="http://localhost:11434"
            )


@pytest.mark.asyncio
async def test_vllm_embed_http_error():
    """Test vLLM embedding handles HTTP errors."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=MagicMock(),
        response=MagicMock()
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="vLLM embedding failed"):
            await vllm_embed(
                texts=["test"],
                model="test-model",
                base_url="http://localhost:8000",
                api_key="wrong-key"
            )
