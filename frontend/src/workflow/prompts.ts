/** Built-in beauty-TVC prompt chips for canvas inspector. */

export type PromptBucket = "brief" | "slogan" | "before" | "after" | "scene";

export const PROMPT_SNIPPETS: Record<
  PromptBucket,
  { id: string; label: string; text: string }[]
> = {
  brief: [
    { id: "soft", label: "柔光特写", text: "高端美妆广告短片，柔光特写，电影感光线" },
    { id: "texture", label: "质地推镜", text: "产品质地特写，缓慢推进，浅景深，广告片质感" },
    { id: "lifestyle", label: "生活场景", text: "自然生活场景中的妆容表达，温暖日光，真实肤感" },
  ],
  slogan: [
    { id: "see", label: "看见自己", text: "看见更好的自己" },
    { id: "glow", label: "水光气色", text: "一抹水光，气色自来" },
    { id: "hold", label: "持妆自信", text: "持妆一整天，自信不掉线" },
  ],
  before: [
    { id: "bare", label: "素颜", text: "素颜自然肤质，淡妆前状态，柔和自然光" },
    { id: "tired", label: "疲惫感", text: "略显疲惫的素颜肌肤，妆前对比铺垫" },
  ],
  after: [
    { id: "glow", label: "气色妆", text: "精致妆容，气色明亮，水光肌，自信微笑" },
    { id: "party", label: "派对妆", text: "晚宴妆容，立体修容，眼神聚焦，高级感" },
    { id: "daily", label: "日常妆", text: "清透日常妆，自然红润，贴近生活" },
  ],
  scene: [
    { id: "hook", label: "开场钩子", text: "特写妆容开场，镜头推进，电影感光线" },
    { id: "product", label: "产品展示", text: "产品瓶身与质地特写，柔焦背景" },
    { id: "outro", label: "收束口号", text: "品牌收束镜头，字幕落点，优雅转场" },
  ],
};
