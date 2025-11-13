PORT ?= 1234
MAX_MODEL_LEN ?= 4096
GPU_MEM_UTIL ?= 0.8
KV_CACHE_DTYPE ?= fp8
MAX_BATCHED_TOKENS ?= 512

deploy-llm:
	uv run vllm serve Qwen/Qwen3-VL-8B-Instruct-FP8 \
		--port $(PORT) \
		--max-model-len $(MAX_MODEL_LEN) \
		--gpu-memory-utilization $(GPU_MEM_UTIL) \
		--kv-cache-dtype $(KV_CACHE_DTYPE) \
		--max-num-batched-tokens $(MAX_BATCHED_TOKENS)

run-autoe2e:
	/home/tyrfly1001/autoe2e/scripts/run_autoe2e.sh 2>&1 | tee /home/tyrfly1001/autoe2e/logs/run_autoe2e.log
