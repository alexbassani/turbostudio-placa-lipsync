# O PACOTE DA PLACA — o Lipsync por trecho rodando numa placa alugada da RunPod (Serverless).
#
# O que é: a mesma receita que roda no PC do Alex (ComfyUI 0.42.1 + o gabarito oficial "LTX-2.3: Imagem e Áudio
# para Vídeo"), embrulhada numa imagem que a RunPod liga só enquanto há trecho na fila. O aluno nunca vê isto:
# o TurboStudio cria o endpoint com a chave dele apontando para esta imagem pública, manda o trecho, traz o vídeo.
#
# Fatos que desenharam este arquivo (a pesquisa de 01/11/2026, registrada em apps/docs/feat/speedcut-aluguel-gpu-nov2026/PLANO.md):
#  · O gabarito usa SÓ nós de fábrica do ComfyUI (55 nós, zero custom node) — por isso a imagem é o ComfyUI puro.
#  · O trabalhador oficial da RunPod (worker-comfyui) devolve só imagens e vem com o ComfyUI 0.34 — não serve
#    (o gabarito pede nós LTX-2.3 do 0.42 e devolve VÍDEO com áudio). Por isso o handler.py é nosso.
#  · Os modelos (≈ 40 GB) vão DENTRO da imagem: o cache de modelo da RunPod só se liga pelo console (um aluno não
#    faz isso) e o volume de rede cobra parado. Limite da RunPod: 80 GB por imagem. A imagem fica em ≈ 50 GB.
#  · A licença LTX-2 Community (§3) permite "reproduce and distribute copies ... in any medium", desde que a cópia
#    da licença vá junto (§3(b)) e as restrições de uso passem adiante (§3(a)); o Gemma pede o arquivo NOTICE.
#    Por isso a pasta /licencas/ existe e o TurboStudio mostra o aviso na tela do aluguel.
#  · A placa: o fp8 de 22B tem 27 GB; em placa de 24 GB ele transborda para a RAM do worker (no PC do Alex o
#    ComfyUI usou 39,7 GB de RAM). A régua da A2 mede em cada placa; não é este arquivo que escolhe.
#
# ⚠️ Versões: o torch sai do índice cu128 SEM pino na primeira construção; a A2 registra a versão que funcionou e
#    pina aqui no mesmo commit. O ComfyUI está pinado no v0.42.1 (o mesmo do PC do Alex, onde o gabarito foi provado).

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    COMFY_DIR=/comfyui

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip git ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv
ENV PATH="/venv/bin:${PATH}"

# O torch com CUDA 12.8 (a RunPod constrói o worker-comfyui com 12.8; os hosts dela aceitam 12.8 a 13.x).
RUN pip install --upgrade pip \
    && pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# O ComfyUI, pinado na mesma versão do PC do Alex.
RUN git clone --depth 1 --branch v0.42.1 https://github.com/comfyanonymous/ComfyUI.git ${COMFY_DIR} \
    && pip install -r ${COMFY_DIR}/requirements.txt

# O que o handler usa: o SDK da RunPod, o cliente HTTP e o baixador da Hugging Face.
RUN pip install runpod requests "huggingface_hub[cli]"

# Os cinco modelos do gabarito, nos nomes EXATOS que o gabarito pede (apps/launcher/src/handlers/gabaritos-comfyui/ltx-2.3-ia2v.api.json).
# Fonte dos caminhos: docs.comfy.org/tutorials/video/ltx/ltx-2-3 (lido em 01/11/2026).
RUN hf download Lightricks/LTX-2.3-fp8 ltx-2.3-22b-dev-fp8.safetensors \
        --local-dir ${COMFY_DIR}/models/checkpoints
RUN hf download Lightricks/LTX-2.3 ltx-2.3-spatial-upscaler-x2-1.1.safetensors \
        --local-dir ${COMFY_DIR}/models/latent_upscale_models
RUN hf download Comfy-Org/ltx-2.3 split_files/loras/ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors \
        --local-dir /tmp/hf-ltx23 \
    && mv /tmp/hf-ltx23/split_files/loras/*.safetensors ${COMFY_DIR}/models/loras/ && rm -rf /tmp/hf-ltx23
RUN hf download Comfy-Org/ltx-2 split_files/loras/gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors \
        split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors \
        --local-dir /tmp/hf-ltx2 \
    && mv /tmp/hf-ltx2/split_files/loras/*.safetensors ${COMFY_DIR}/models/loras/ \
    && mv /tmp/hf-ltx2/split_files/text_encoders/*.safetensors ${COMFY_DIR}/models/text_encoders/ \
    && rm -rf /tmp/hf-ltx2

# As licenças viajam com os pesos (LTX-2 Community License §3(b); Gemma Terms of Use: o NOTICE).
COPY licencas/ /licencas/

COPY handler.py /handler.py

# Portão de sanidade na construção: os cinco arquivos existem, o Python compila e o torch diz a versão (a A2 pina esta).
# ⚠️ NÃO importar o ComfyUI aqui: o comfy.model_management procura a placa ao ser importado, e a construção roda SEM placa
# ("Found no NVIDIA driver", a falha real de 01/11/2026). Quem prova o ComfyUI de pé é o primeiro trecho na placa.
RUN test -s ${COMFY_DIR}/models/checkpoints/ltx-2.3-22b-dev-fp8.safetensors \
    && test -s ${COMFY_DIR}/models/latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors \
    && test -s ${COMFY_DIR}/models/loras/ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors \
    && test -s ${COMFY_DIR}/models/loras/gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors \
    && test -s ${COMFY_DIR}/models/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors \
    && python -m py_compile /handler.py ${COMFY_DIR}/main.py \
    && python -c "import runpod, requests, torch; print('torch', torch.__version__, 'cuda', torch.version.cuda)"

WORKDIR /
CMD ["python", "-u", "/handler.py"]
