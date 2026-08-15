/** User-facing names. Keep short and concrete; avoid product jargon. */

export const NODE_TYPE_LABEL: Record<string, string> = {
  TextAsset: "文案",
  ImageAsset: "图片",
  VideoAsset: "视频",
  AudioAsset: "配乐",
  LlmText: "写镜头",
  TextToImage: "出图",
  ImageToVideo: "出视频",
  ImageCompare: "对比图",
  SpeechToText: "听写",
  TtsSpeak: "配音",
  VideoTrim: "裁视频",
  AudioTrim: "裁音频",
  VideoMux: "拼接",
  VideoDemux: "拆声音",
  VideoReversePrompt: "拆参考片",
  MixAudio: "混音",
  SubtitleBurn: "加字幕",
};

export const NODE_TYPE_HINT: Record<string, string> = {
  TextAsset: "写品牌、卖点和口号",
  ImageAsset: "上传产品图或人物图",
  VideoAsset: "上传参考片或成片",
  AudioAsset: "上传背景音乐或旁白",
  LlmText: "让模型写这一镜的画面和口播",
  TextToImage: "按文字生成首帧图",
  ImageCompare: "两张图里选一张继续用",
  SpeechToText: "从片子里抽出解说词",
  ImageToVideo: "一张图变成一段视频",
  TtsSpeak: "把文案念成口播",
  VideoTrim: "截取需要的几秒",
  AudioTrim: "截取需要的几秒",
  VideoMux: "把几段视频接成一条",
  VideoDemux: "把声音从画面里拆出来",
  VideoReversePrompt: "看参考片，拆出分镜",
  MixAudio: "把画面、配乐、口播合在一起",
  SubtitleBurn: "在成片上叠一句字",
};

export function nodeTypeLabel(nodeType: string): string {
  return NODE_TYPE_LABEL[nodeType] || nodeType;
}
