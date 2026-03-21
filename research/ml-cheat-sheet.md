# ML Concepts Cheat Sheet

*From the March 20, 2026 session. Written for future-me who will forget all of this.*

## The Big Picture

Everything in modern AI is built on **transformers** (2017, "Attention Is All You Need"). Before transformers, models processed sequences one token at a time (RNNs). Transformers process all tokens simultaneously by letting every token look at every other token. This is called **attention**.

The transformer architecture is domain-agnostic. It operates on **sequences of vectors**. How you get into vector space is the only difference:
- **LLM**: text → tokenizer → vectors
- **ViT**: image → chop into patches → vectors
- **LMM** (multimodal): both tokenizers → concatenate → same transformer

Once in vector space, the architecture is identical. That's why multimodal models work.

## Core Concepts

### Transformer
An architecture that transforms vectors by mixing information between them via attention. Stack 80+ layers deep. Each layer refines every vector with more contextual awareness.

**Heuristic**: A transformer is a context-mixing machine. Raw embeddings go in, context-saturated representations come out.

### Attention
The mechanism inside a transformer. Each token produces three vectors from learned matrices:
- **Query** — "what am I looking for?"
- **Key** — "what do I offer?"
- **Value** — "what information do I contain?"

Attention score = dot product of one token's Query with another's Key. High score = high relevance. Each token then takes a weighted sum of all Values, weighted by attention scores.

**Heuristic**: Query × Key = "how relevant are you to me?" Value = "here's what I actually contribute." The matrices that produce Q, K, V are the learned parameters — they ARE the model.

### Multi-Head Attention
Multiple sets of Q/K/V matrices running in parallel on the same input. Each "head" learns to attend to different kinds of relationships (syntactic, semantic, positional). Results get concatenated.

**Heuristic**: Multiple independent perspectives on the same sequence, simultaneously.

### Embedding
A vector representation of a token. The word "Monacan" becomes something like [0.3, 0.8, 0.1, ...] — a list of numbers in high-dimensional space. Similar concepts end up near each other.

### Vocabulary
A fixed set of tokens the model can work with (~50K-100K). Every possible output is scored simultaneously — the model produces a probability for every token in the vocabulary, then picks the highest (or samples).

### Learned Linear Projection
A matrix multiplication where the matrix values were adjusted during training. "Linear" = just multiply and add, no curves. "Projection" = maps vectors from one space to another. "Learned" = started random, got useful through training.

## Training

### How It Works
1. Start with a complete architecture — all matrices exist but filled with random numbers
2. Feed in text, model predicts next token (terribly at first)
3. **Loss function** measures how wrong the prediction was
4. **Backpropagation** traces backward through every matrix: "which numbers contributed to this wrong answer? which direction should I nudge them?"
5. Nudge all numbers by a tiny amount (like 0.0001) in the direction that reduces error
6. Repeat billions of times across terabytes of text

**Heuristic**: Training = "guess the next word, see how wrong you were, adjust slightly, repeat." Everything the model knows emerges from this single game.

### What Gets Trained
The matrices — all of them. Embedding matrices, attention Q/K/V matrices, feedforward layers, output layers. Billions of parameters, each nudged billions of times. Nobody programs what they mean; useful representations emerge from the training signal.

### Scale
Foundation models (GPT-4, Claude) cost $100M+ to train on trillions of tokens across thousands of GPUs. You never train from scratch for a niche domain.

## Specializing a Model

### Fine-Tuning (LoRA)
**Low-Rank Adaptation.** Freeze the original model weights. Add tiny new matrices alongside them. Train only the new matrices on your domain data.

```
Final output = original_output + adapter_output
```

Both run every time — there's no routing. The original provides general knowledge, the adapter applies a thin domain-specific correction.

**Heuristic**: LoRA is like putting domain-specific glasses on the model. The model's eyes (weights) don't change. The glasses (adapter) adjust what it focuses on.

### RAG (Retrieval-Augmented Generation)
Don't change the model at all. At query time, retrieve relevant documents and stuff them into the prompt as context. The model reads them and generates an answer grounded in that context.

### LoRA vs RAG

| | **RAG** | **LoRA** |
|---|---|---|
| Changes | The input (prompt) | The model (weights) |
| When | Every query | Once during training |
| Can cite sources | Yes | No — knowledge baked into weights |
| Updatable | Change the docs | Retrain |
| Cost | Per-query | One-time |

**Heuristic**: RAG = "read this before answering." LoRA = "I've permanently adjusted how you think." You can combine both.

## Vision Models

### CNN (Convolutional Neural Network)
Slides small filters across an image, layer by layer. Builds understanding locally and bottom-up: edges → shapes → objects. Good at texture and local features.

### ViT (Vision Transformer)
Chops image into patches (e.g. 16×16 pixels), treats each patch as a token, runs transformer attention over all patches. Every patch can attend to every other patch from layer one — global context immediately.

### CNN vs ViT
- CNNs are more data-efficient (better with small datasets, ~50 images per class)
- ViTs tend to win with lots of training data
- Both perform similarly in practice for most tasks
- Some architectures (ConvNeXt) blend both approaches

### CLIP
Combines a ViT + a text encoder. Trained to match images with text descriptions. Zero-shot classification: give it an image and text labels ("projectile point", "ceramic sherd"), it picks the best match. No training needed, runs locally.

## Classification

### Softmax
Converts scores into probabilities that **sum to 1**. Forces picking one category. Use for single-label classification ("this IS a cat, NOT a dog").

### Sigmoid
Each label gets an **independent probability** between 0 and 1. Multiple labels can be high simultaneously. Use for multi-label classification.

**Heuristic**: Softmax = "pick one." Sigmoid = "check all that apply."

### Multi-Label Classification
What the debitage classifier needs. A single artifact photo can be FLA + TAL + EWN simultaneously. Use sigmoid output, not softmax. Threshold at ~0.5 — everything above = yes.

## BERT vs GPT (Encoder vs Decoder)

### BERT (2018)
Bidirectional — sees entire input at once. Good for understanding, classification, embeddings. Requires labeled training data for fine-tuning. Lineage lives on in embedding models (nomic, sentence-transformers).

### GPT
Left-to-right — predicts next token. Good for generation. Can do zero-shot tasks via prompting (no training data needed).

**Heuristic**: BERT-lineage = understanding/encoding. GPT-lineage = generation. Modern stacks use both: BERT-style for embeddings, GPT-style for generation. Your archaeology pipeline does exactly this (nomic for chunk embeddings, Claude for NER/synthesis).

## Why Transformers Took Until 2017

1. **Attention existed before** (2014) — but as an add-on to RNNs, not a replacement
2. **GPUs weren't ready** — attention is O(n²), prohibitively expensive before ~2016 hardware
3. **RNNs kept getting patched** — LSTMs, attention-augmented RNNs extended their life
4. **Sequential processing felt natural** for sequential data — the leap was realizing you can encode position as metadata instead of processing order
