"""O programa que roda DENTRO da placa alugada (RunPod Serverless) para o Lipsync por trecho.

Recebe um pedido, dá para o ComfyUI que mora na mesma máquina, espera, e devolve o vídeo. Nada mais.

Entrada (o `input` do job da RunPod):
    pedido        — o fluxo em formato de API (o gabarito já montado pelo TurboStudio, trecho a trecho)
    arquivos      — [{"nome": "quadro.png", "base64": "..."}, ...]: a imagem e o áudio do trecho, gravados em ComfyUI/input
    limite_seg    — (opcional) quantos segundos esperar pelo ComfyUI antes de desistir (padrão 900)

Saída:
    {"ok": true, "video_base64": "...", "nome": "ltx23_00001_.mp4", "bytes": 3012345, "segundos": 71.2}
    {"ok": false, "erro": "em palavras", "detalhe": "...", "segundos": 12.0}

Por que devolve em base64 e não por S3: o vídeo de um trecho de 8 s em 720p mede ≈ 3 MB (medido no PC do Alex:
5 s = 1,9 MB), e o limite da RunPod para a resposta do /run é 10 MB. Cabe com folga, sem o aluno precisar de
balde S3. Se um dia o trecho crescer, o limite está em TAMANHO_MAXIMO_SAIDA e o erro sai em palavras.

Regras da casa que este arquivo obedece:
  · erro em palavras (o TurboStudio mostra na tela; nunca o traceback cru);
  · nenhum segredo aqui: a chave da RunPod fica no cofre do TurboStudio, e a RunPod chama este programa;
  · o ComfyUI sobe UMA vez, no boot do worker; cada job só enfileira e espera.
"""

import base64
import json
import os
import subprocess
import sys
import time
import uuid

import requests
import runpod

COMFY_DIR = os.environ.get("COMFY_DIR", "/comfyui")
COMFY_URL = "http://127.0.0.1:8188"
TAMANHO_MAXIMO_ENTRADA = 9 * 1024 * 1024   # o /run aceita 10 MB no total
TAMANHO_MAXIMO_SAIDA = 9 * 1024 * 1024     # idem para a resposta
ESPERA_PADRAO_SEG = 900
_processo_comfy = None


def _log(msg):
    print("[placa-lipsync] " + msg, flush=True)


# ---------------------------------------------------------------- o ComfyUI sobe uma vez

def subir_comfyui():
    """Liga o ComfyUI em segundo plano e espera o /system_stats responder (o modelo só carrega no 1º pedido)."""
    global _processo_comfy
    if _processo_comfy is not None and _processo_comfy.poll() is None:
        return
    _log("subindo o ComfyUI " + COMFY_DIR)
    _processo_comfy = subprocess.Popen(
        [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch",
         "--disable-metadata"],
        cwd=COMFY_DIR, stdout=sys.stdout, stderr=sys.stderr,
    )
    inicio = time.time()
    while time.time() - inicio < 600:
        if _processo_comfy.poll() is not None:
            raise RuntimeError("O ComfyUI fechou ao subir (código " + str(_processo_comfy.returncode) + ")")
        try:
            r = requests.get(COMFY_URL + "/system_stats", timeout=3)
            if r.ok:
                _log("ComfyUI pronto em %.0f s" % (time.time() - inicio))
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("O ComfyUI não respondeu em 10 minutos")


def comfy_vivo():
    return _processo_comfy is not None and _processo_comfy.poll() is None


# ---------------------------------------------------------------- o pedido

def gravar_arquivos(arquivos):
    pasta = os.path.join(COMFY_DIR, "input")
    os.makedirs(pasta, exist_ok=True)
    total = 0
    for a in arquivos or []:
        nome = os.path.basename(str(a.get("nome") or ""))
        if not nome or nome.startswith("."):
            raise ValueError("Um arquivo veio sem nome")
        dados = base64.b64decode(a.get("base64") or "", validate=False)
        total += len(dados)
        if total > TAMANHO_MAXIMO_ENTRADA:
            raise ValueError("Os arquivos do trecho passam de 9 MB")
        with open(os.path.join(pasta, nome), "wb") as f:
            f.write(dados)
    return total


def enfileirar(pedido):
    client_id = str(uuid.uuid4())
    r = requests.post(COMFY_URL + "/prompt", json={"prompt": pedido, "client_id": client_id}, timeout=60)
    if r.status_code != 200:
        detalhe = r.text[:2000]
        try:
            j = r.json()
            erros = j.get("node_errors") or {}
            if erros:
                primeiro = next(iter(erros.values()))
                e0 = (primeiro.get("errors") or [{}])[0]
                detalhe = (e0.get("message") or "") + " " + (e0.get("details") or "")
            elif j.get("error"):
                detalhe = str(j["error"].get("message") or j["error"])
        except ValueError:
            pass
        raise RuntimeError("O ComfyUI recusou o pedido: " + detalhe.strip())
    return r.json()["prompt_id"]


def esperar(prompt_id, limite_seg):
    """Espera o histórico dizer que acabou. Sem resposta do ComfyUI por 60 s seguidos = ele morreu (o SC-43 ensinou)."""
    inicio = time.time()
    sem_resposta_desde = None
    while True:
        if time.time() - inicio > limite_seg:
            raise TimeoutError("O trecho passou de %d s e foi cancelado" % limite_seg)
        if not comfy_vivo():
            raise RuntimeError("O ComfyUI fechou no meio do trecho")
        try:
            r = requests.get(COMFY_URL + "/history/" + prompt_id, timeout=10)
            sem_resposta_desde = None
            if r.ok:
                h = r.json().get(prompt_id)
                if h:
                    status = h.get("status") or {}
                    if status.get("status_str") == "error":
                        raise RuntimeError("O ComfyUI parou com erro: " + _erro_em_palavras(status))
                    if status.get("completed") or h.get("outputs"):
                        return h
        except requests.RequestException:
            sem_resposta_desde = sem_resposta_desde or time.time()
            if time.time() - sem_resposta_desde > 60:
                raise RuntimeError("O ComfyUI parou de responder")
        time.sleep(2)


def _erro_em_palavras(status):
    for m in status.get("messages") or []:
        if isinstance(m, list) and len(m) == 2 and m[0] == "execution_error":
            d = m[1] or {}
            return (d.get("exception_message") or d.get("exception_type") or "sem detalhe")[:1500]
    return "sem detalhe"


def achar_video(historico):
    """O SaveVideo do ComfyUI 0.42 anuncia o arquivo em outputs[...]["images"] (com animated) ou ["videos"]."""
    for saida in (historico.get("outputs") or {}).values():
        for chave in ("videos", "gifs", "images"):
            for item in saida.get(chave) or []:
                nome = item.get("filename") or ""
                if nome.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
                    return os.path.join(COMFY_DIR, "output", item.get("subfolder") or "", nome), nome
    raise RuntimeError("O fluxo terminou sem gravar vídeo")


# ---------------------------------------------------------------- o handler

def handler(job):
    inicio = time.time()
    entrada = job.get("input") or {}
    try:
        pedido = entrada.get("pedido")
        if not isinstance(pedido, dict) or not pedido:
            raise ValueError("O pedido veio vazio")
        limite = int(entrada.get("limite_seg") or ESPERA_PADRAO_SEG)
        subir_comfyui()
        gravar_arquivos(entrada.get("arquivos"))
        runpod.serverless.progress_update(job, "gerando")
        prompt_id = enfileirar(pedido)
        historico = esperar(prompt_id, limite)
        caminho, nome = achar_video(historico)
        tamanho = os.path.getsize(caminho)
        if tamanho > TAMANHO_MAXIMO_SAIDA:
            raise RuntimeError("O vídeo saiu com %.1f MB, acima do que a resposta carrega" % (tamanho / 1048576))
        with open(caminho, "rb") as f:
            video = base64.b64encode(f.read()).decode("ascii")
        try:
            os.remove(caminho)
        except OSError:
            pass
        return {"ok": True, "video_base64": video, "nome": nome, "bytes": tamanho,
                "segundos": round(time.time() - inicio, 1)}
    except Exception as e:  # noqa: BLE001 — tudo vira resposta em palavras; a RunPod não vê traceback
        _log("falhou: " + repr(e))
        return {"ok": False, "erro": str(e)[:500] or e.__class__.__name__, "detalhe": e.__class__.__name__,
                "segundos": round(time.time() - inicio, 1)}


if __name__ == "__main__":
    try:
        subir_comfyui()
    except Exception as e:  # o boot falhou: a RunPod reinicia o worker; o log diz por quê
        _log("o ComfyUI não subiu no boot: " + repr(e))
    runpod.serverless.start({"handler": handler})
