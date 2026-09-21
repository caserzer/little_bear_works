# 生活英语样音 V2：更自然的年轻女声，语速加快

实测时长 **2分14秒**，316词，含停顿平均约142词/分钟。第一版为3分10秒、约100词/分钟。

根据试听反馈“音色太幼年、语速偏慢”制作。沿用同一篇《One More, Please!》，方便直接比较声音和节奏；仍为生活场景，尚未生成完整40集。

- [试听新版MP3](sample_v2_one_more_please.mp3)
- [试听页](试听.html)
- [原文](sample.txt)
- [英文字幕](sample_v2_one_more_please.srt)
- [第一版音频，供对比](../sample_one_more_please.mp3)

声音从 Ana 改为 Michelle（en-US-MichelleNeural，美式英语女声），方向为更接近青少年感的清亮、自然表达。语速参数由旧声音的 -8% 改为新声音的 +20%，音高保持原始值。不同声音的基准速度不同，实际变化以同篇稿件的实测时长为准。

“青少年感”是本次选音目标，服务元数据未注明精确年龄，不将其宣称为特定年龄的真人声音。最终是否符合你希望的十几岁感觉，以试听反馈为准。全部角色仍由同一旁白声音演绎，无配乐。

核验记录见 generation_receipt.json，包括实际时长、MP3完整解码、峰值和字幕全文一致性。尚未人工试听确认音色喜好。

复现：

~~~bash
/tmp/little-bear-audio-venv/bin/python grade6/English/listening/2026-09-21_little_moments_sample/v2/generate_sample.py
~~~
