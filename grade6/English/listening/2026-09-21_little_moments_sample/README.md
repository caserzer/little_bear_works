# Little Moments · 生活英语样音

本次先交付1集样音，供确认生活化程度、声音和语速。新一季目标为40集，每集不超过20分钟；其余集数待试听反馈后制作。

**最新：[V3样音：四人分角色配音](v3/README.md)。Lucy、爸爸、店员和弟弟使用四种不同声音，延续V2加快的语速。**

前一轮：[V2样音：年轻女声与更快语速](v2/README.md)。以下保留第一版说明，便于比较。

## 试听

样音实测3分10秒，约316词；含对白停顿的平均语速约100词/分钟。

- [播放或下载MP3：One More, Please!](sample_one_more_please.mp3)
- [打开试听页](试听.html)
- [英文原文](sample.txt)
- [英文字幕](sample_one_more_please.srt)

**场景：周六和爸爸到面包店买早餐。** Lucy第一次自己点单，临时想起弟弟也要一份，还看中了长得像自家猫咪的小饼干。

使用常见日常口语、短句和自然重复；本集保持一个连贯故事，不插入科普讲解、语法讲授或集中练习。声音为AI合成的美式女童风格旁白，单一声音叙述全部角色对白，无背景音乐。

## 会听到的生活表达

| 表达 | 意思 |
|---|---|
| What can I get for you? | 想要点什么？ |
| Could I have two cinnamon rolls, please? | 请给我两个肉桂卷，好吗？ |
| For here or to go? | 在这里吃还是带走？ |
| Actually, could we make that three? | 我想改成三个，可以吗？ |
| Let's stick with the rolls today. | 今天就买肉桂卷吧。 |
| Could we have a few napkins, please? | 可以给我们几张餐巾纸吗？ |

故事中的价格、人物与店铺为虚构。Lucy's cat Noodle是虚构宠物，不使用孩子或家庭的真实身份信息。

## 试听后可以反馈

1. 声音：是否够可爱、是否过于幼龄，或希望更接近自然少女声？
2. 语速：是否舒服，是否需要再慢一些？
3. 内容：这样的买早餐、家庭互动与小幽默是否合适？

后续可扩展到起床、穿衣、早餐、上学、同学相处、购物、乘车、做家务、宠物、运动、外出吃饭和周末活动。此处只是方向，尚未批量生成。

## 制作说明

声音：en-US-AnaNeural；美式英语；语速参数 -8%；音高参数 +0Hz，保留该声音原始音高。微软将该声音列为Female, Child，见[官方声音列表](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support)。主观的可爱程度和舒适度以本次试听反馈为准。

使用[edge-tts](https://github.com/rany2/edge-tts) 7.2.8生成。实测时长、文本与音频校验值、解码和字幕一致性检查见 generation_receipt.json。技术检查不等同于人工试听或对表达效果的主观评分。

重新生成样音：

~~~bash
/tmp/little-bear-audio-venv/bin/python grade6/English/listening/2026-09-21_little_moments_sample/generate_sample.py
~~~

生成依赖联网，以及 edge-tts、ffmpeg、ffprobe。下载完成的MP3可离线播放。
