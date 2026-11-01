# O pacote da placa: o Lipsync por trecho na RunPod

Esta pasta é a **fonte** do pacote que roda numa placa alugada. O aluno nunca a vê: o TurboStudio cria o endpoint
na conta dele apontando para a imagem pública construída daqui, manda cada trecho, e traz o vídeo de volta.

| Arquivo | O que é |
|---|---|
| `Dockerfile` | A receita da imagem: CUDA 12.8 + ComfyUI v0.42.1 (o mesmo do PC do Alex) + os 5 modelos do gabarito (≈ 40 GB) + as licenças |
| `handler.py` | O programa que a RunPod chama por job: grava a imagem e o áudio do trecho, enfileira o pedido no ComfyUI, espera, devolve o mp4 em base64 |
| `licencas/` | A LTX-2 Community License e o NOTICE do Gemma, que viajam dentro da imagem (obrigação das duas licenças) |

O plano inteiro, as travas e o roteiro de teste: [`apps/docs/feat/speedcut-aluguel-gpu-nov2026/PLANO.md`](../../../../docs/feat/speedcut-aluguel-gpu-nov2026/PLANO.md).

## O contrato do job

```json
{ "input": { "pedido": { "...o gabarito em formato de API, já montado pelo TurboStudio..." },
             "arquivos": [ { "nome": "quadro.png", "base64": "..." }, { "nome": "trecho.wav", "base64": "..." } ],
             "limite_seg": 900 } }
```

Resposta: `{ "ok": true, "video_base64": "...", "nome": "ltx23_00001_.mp4", "bytes": 3012345, "segundos": 71.2 }`
ou `{ "ok": false, "erro": "em palavras", "detalhe": "RuntimeError", "segundos": 12.0 }`.

Limites (da RunPod, lidos em 01/11/2026): o `/run` aceita 10 MB de pedido e 10 MB de resposta. Um trecho de 8 s
em 720p mede ≈ 3 MB (medido: 5 s = 1,9 MB). O handler recusa em palavras o que passar de 9 MB.

## Onde a imagem é construída (não há Docker no PC do Alex, e não precisa)

1. **Para a régua da A2 (a conta dele, US$ 10):** a *GitHub integration* da RunPod constrói a imagem na nuvem a
   partir deste Dockerfile, sem Docker local. É só no console: *Serverless → New Endpoint → Import Git Repository*.
   Limites dela: a etapa `docker build` em 30 min, o total em 160 min, imagem até 80 GB. ⚠️ O download dos 40 GB
   pode passar dos 30 min do `build` — se passar, o caminho 2 vale para a A2 também.
   A imagem construída assim fica no registro privado da conta dele: serve para medir, **não** serve para o aluno.
2. **Para os alunos (a imagem PÚBLICA):** construir numa máquina alugada da RunPod (um Pod de CPU por uma hora,
   centavos) com o `buildah` (sem daemon) e empurrar para o Docker Hub público `turbostudio/placa-lipsync`. A
   RunPod documenta o caminho equivalente com Bazel; o buildah é a tentativa 1, o Bazel a 2, e o Docker Desktop no
   PC do Alex (WSL2, 50 GB de upload) a 3. Isso é a etapa A3.

Pinos que a A2 fecha: a versão do torch que funcionou (o Dockerfile instala a mais nova do índice cu128 na primeira
construção) e a placa que o pacote exige (o fp8 de 22 B tem 27 GB; em placa de 24 GB ele transborda para a RAM).

## Licenças que viajam na imagem

- **LTX-2 Community License** (`licencas/LTX-2-COMMUNITY-LICENSE.txt`): §3 permite reproduzir e distribuir cópias
  "in any medium"; §3(b) exige a cópia da licença junto; §3(a) exige passar as restrições de uso adiante (o
  TurboStudio mostra o aviso na tela do aluguel); §2: entidades com receita ≥ US$ 10 milhões precisam de licença
  paga; Anexo A, item 20: não usar em produto que "directly competes" com a Lightricks sem licença separada.
- **Gemma Terms of Use** (`licencas/NOTICE-GEMMA.txt`): distribuição fora de serviço hospedado exige o arquivo
  NOTICE dizendo que o Gemma é fornecido sob os Gemma Terms, e passar as restrições de uso da §3.2 adiante.
