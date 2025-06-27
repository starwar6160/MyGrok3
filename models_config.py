# --- Model Name Constants ---
GEMINI_FLASH_1_5_8B = "google/gemini-flash-1.5-8b"
GEMINI_2_5_FLASH_LITE = "google/gemini-2.5-flash-lite-preview-06-17"
GEMMA_3_12B_IT = "google/gemma-3-12b-it"
GEMMA_3_27B_IT_FREE = "google/gemma-3-27b-it:free"
QWEN3_32B_FREE = "qwen/qwen3-32b:free"
KIMI_DEV_72B_FREE = "moonshotai/kimi-dev-72b:free"
GPT_4O_MINI = "openai/gpt-4o-mini"
GROK_3_MINI = "x-ai/grok-3-mini"
DEEPSEEK_R1_DISTILL_LLAMA_70B_FREE = "deepseek/deepseek-r1-distill-llama-70b:free"
DEEPSEEK_R1_0528_FREE = "deepseek/deepseek-r1-0528:free"
UNSLOPNEMO_12B = "thedrummer/unslopnemo-12b"

# --- Model Lists ---

MODELS_EXPERIMENTAL = [
    # Gemini models
    GEMINI_2_5_FLASH_LITE,
    GEMINI_FLASH_1_5_8B,    
    GEMMA_3_12B_IT,
    GEMMA_3_27B_IT_FREE,

    # Other models
    QWEN3_32B_FREE,
    KIMI_DEV_72B_FREE,

    # General economic models
    GPT_4O_MINI,
    GROK_3_MINI,
    DEEPSEEK_R1_DISTILL_LLAMA_70B_FREE,
    DEEPSEEK_R1_0528_FREE,
]

MODELS_STABLE = [
    GEMINI_2_5_FLASH_LITE,
    GEMINI_FLASH_1_5_8B,
    GROK_3_MINI,
    GPT_4O_MINI,
    DEEPSEEK_R1_DISTILL_LLAMA_70B_FREE,
]

# --- Specific Model Roles ---
TRANSLATION_MODEL = GEMINI_FLASH_1_5_8B
ENGLISH_MODEL = UNSLOPNEMO_12B
# ENGLISH_MODEL = GEMINI_2_5_FLASH_LITE # Alternative

