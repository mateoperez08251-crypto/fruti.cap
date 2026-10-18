"""Qwen 2.1 BF16 scene graph, using native nodes in the pinned ComfyUI commit.

Based on Comfy-Org/workflow_templates at 59a3b48bf369c5a15f29a1308bae3e279fa15505.
Scene composition deliberately uses a custom canvas, not the first reference's size.
No prompt enhancer, Lightning, or external custom nodes are required.
"""

T2I_WORKFLOW = "QWEN_21_T2I.api.json"
EDIT_WORKFLOW = "QWEN_21_EDIT.api.json"
WORKFLOWS = (T2I_WORKFLOW, EDIT_WORKFLOW)
PROFILE = "qwen21_bf16"
WIDTH, HEIGHT = 1152, 2048


def build_graph():
    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    return {
        "model": node("UNETLoader", unet_name="qwen_image_2.1_bf16.safetensors", weight_dtype="default"),
        "clip": node(
            "CLIPLoader", clip_name="qwen3vl_8b_bf16.safetensors", type="qwen_image", device="default"
        ),
        "vae": node("VAELoader", vae_name="qwen_image_2.1_vae_bf16.safetensors"),
        "encode": node(
            "TextEncodeQwenImage21",
            clip=["clip", 0],
            vae=["vae", 0],
            prompt="A strawberry character in a sunlit market.",
            negative_prompt="",
            resolution=1024,
        ),
        "cache": node("QwenImage21Cache", model=["model", 0], device="auto", dtype="default"),
        "canvas": node("EmptyLatentImage", width=WIDTH, height=HEIGHT, batch_size=1),
        "sampler": node(
            "KSampler",
            model=["cache", 0],
            positive=["encode", 0],
            negative=["encode", 1],
            latent_image=["canvas", 0],
            seed=42,
            steps=40,
            cfg=1.0,
            sampler_name="euler",
            scheduler="simple",
            denoise=1.0,
        ),
        "decode": node("VAEDecode", samples=["sampler", 0], vae=["vae", 0]),
        "rgb": node("SplitImageWithAlpha", image=["decode", 0]),
        "save": node("SaveImage", images=["rgb", 0], filename_prefix="FRUTINOVELAS/Qwen21"),
    }
