/** Beauty TVC promo assets & prompt templates (placeholder stock for MVP). */

export type BeautyPromo = {
  id: string;
  title: string;
  tag: string;
  brand: string;
  description: string;
  image: string;
  prompt: string;
  duration: number;
};

export const BEAUTY_PROMOS: BeautyPromo[] = [
  {
    id: "lip-velvet",
    title: "丝绒唇釉特写",
    tag: "唇妆",
    brand: "ROUGE ATELIER",
    description: "唇部微距推进，光泽随呼吸轻微颤动，突出色号与质地。",
    image: "/beauty/lipstick.jpg",
    prompt:
      "Extreme close-up beauty TVC of velvet matte lipstick on soft lips, dew-like skin texture, slow push-in, soft beauty lighting, luxury cosmetics commercial, 4k",
    duration: 5,
  },
  {
    id: "serum-glow",
    title: "精华滴落光感",
    tag: "护肤",
    brand: "LUMINA LAB",
    description: "滴管落下、肌肤吸收的通透感，适合功效型面部精华广告。",
    image: "/beauty/serum.jpg",
    prompt:
      "Cinematic facial skincare TVC, glass dropper releasing serum onto glowing cheek, translucent skin, soft rim light, clean beauty commercial look",
    duration: 6,
  },
  {
    id: "perfume-aura",
    title: "香氛瓶身氛围",
    tag: "香氛",
    brand: "NOIR ÉCLAT",
    description: "玻璃瓶折射与轻烟流转，打造高级香氛 TVC 开场。",
    image: "/beauty/perfume.jpg",
    prompt:
      "Luxury perfume bottle on wet marble, soft morning light, subtle mist, elegant beauty fragrance TVC product hero shot, shallow depth of field",
    duration: 5,
  },
  {
    id: "base-skin",
    title: "底妆贴合演示",
    tag: "底妆",
    brand: "VEIL SKIN",
    description: "妆前到上妆的面部贴合过程，强调自然裸感与遮瑕力。",
    image: "/beauty/face-beauty.jpg",
    prompt:
      "Beauty influencer applying lightweight foundation on face, natural skin finish, soft window light, facial makeup TVC, elegant slow motion",
    duration: 8,
  },
  {
    id: "palette-play",
    title: "彩盘开合运镜",
    tag: "彩妆",
    brand: "CHROMA BOX",
    description: "眼影盘开合与刷具扫过，色彩层次适合短视频种草。",
    image: "/beauty/makeup-kit.jpg",
    prompt:
      "Top-down beauty TVC of eyeshadow palette opening, soft brushes sweeping pigments, colorful cosmetics flat lay, glossy commercial lighting",
    duration: 5,
  },
  {
    id: "blush-flush",
    title: "腮红气色递进",
    tag: "面妆",
    brand: "FLUSH RITUAL",
    description: "面中气色由浅入深，突出面部轮廓与好气色卖点。",
    image: "/beauty/blush.jpg",
    prompt:
      "Close-up facial beauty commercial, soft peach blush applied to cheekbones, healthy flush, beauty model, soft pastel background, luxury makeup ad",
    duration: 6,
  },
  {
    id: "skincare-set",
    title: "护肤套组陈列",
    tag: "套组",
    brand: "PURE LAYER",
    description: "瓶罐陈列与手部拿取，适合电商主图视频与套组推广。",
    image: "/beauty/skincare.jpg",
    prompt:
      "Clean skincare product set on ceramic tray, hand picking serum bottle, soft daylight, minimal beauty still-life TVC, premium cosmetics",
    duration: 5,
  },
  {
    id: "gloss-shine",
    title: "唇蜜高光反射",
    tag: "唇妆",
    brand: "GLASS LIP",
    description: "唇蜜拉丝与高光反射，强化水光唇卖点。",
    image: "/beauty/gloss.jpg",
    prompt:
      "Macro beauty shot of glossy lip oil on lips, glass-like shine, slow motion stretch of gloss, high-end lip beauty TVC, crisp lighting",
    duration: 5,
  },
];

export const BEAUTY_TAGS = ["全部", "唇妆", "底妆", "面妆", "护肤", "彩妆", "香氛", "套组"] as const;
