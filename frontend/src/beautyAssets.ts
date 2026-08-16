/** Beauty TVC promo assets & prompt templates (placeholder stock for MVP). */

export type LookbookKind = "beauty" | "hardware";

export type BeautyPromo = {
  id: string;
  title: string;
  tag: string;
  brand: string;
  description: string;
  image: string;
  prompt: string;
  duration: number;
  kind?: LookbookKind;
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

export const HARDWARE_PROMOS: BeautyPromo[] = [
  {
    id: "hw-cnc",
    title: "CNC 铝合金机身",
    tag: "结构件",
    brand: "FORGE LAB",
    kind: "hardware",
    description: "阳极氧化铝件特写，突出开模精度与散热孔，适合 3C 结构件主片。",
    image: "/hardware/cnc-body.jpg",
    prompt:
      "Industrial hardware TVC, CNC machined aluminum unibody on a dark bench, brushed metal, heat vents and screw seats, cool workshop overhead light, Shenzhen maker commercial, 16:9",
    duration: 5,
  },
  {
    id: "hw-pcb",
    title: "板卡贴装工位",
    tag: "板卡",
    brand: "TRACE BOARD",
    kind: "hardware",
    description: "ESD 台面上的 PCB 与贴装细节，适合模组、电源、控制板种草。",
    image: "/hardware/pcb-bench.jpg",
    prompt:
      "Close-up electronics TVC of a green PCB on an ESD mat, chips and connectors in focus, soldering station bokeh, cool practical light, hardware lab commercial",
    duration: 6,
  },
  {
    id: "hw-workshop",
    title: "科创工坊全景",
    tag: "工坊",
    brand: "科创工坊",
    kind: "hardware",
    description: "工位、打样设备与动手场景，对标深圳科创学院宣传片开场。",
    image: "/hardware/workshop.jpg",
    prompt:
      "Shenzhen hardware academy workshop TVC, benches with 3D printers and CNC, students assembling prototypes, documentary-commercial lighting, 16:9",
    duration: 8,
  },
  {
    id: "hw-drone",
    title: "无人机静物",
    tag: "无人机",
    brand: "AIRFRAME",
    kind: "hardware",
    description: "碳纤机架与桨叶静物，适合航拍器、机器人开场英雄镜。",
    image: "/hardware/drone.jpg",
    prompt:
      "Product hero of a compact carbon-fiber quadcopter on concrete, still props, cool rim light, industrial hardware commercial, no text",
    duration: 5,
  },
  {
    id: "hw-wearable",
    title: "可穿戴表体",
    tag: "可穿戴",
    brand: "PULSE RIG",
    kind: "hardware",
    description: "钛合金表耳与充电触点微距，适合手表、手环、传感器模组。",
    image: "/hardware/wearable.jpg",
    prompt:
      "Macro hardware TVC of a matte titanium smartwatch, metal lugs and pogo pins, cool daylight, premium electronics still, 16:9",
    duration: 5,
  },
  {
    id: "hw-proto",
    title: "打样件对照",
    tag: "样机",
    brand: "ITER ATELIER",
    kind: "hardware",
    description: "光固化外壳与金属嵌件并置，强调从想法到可装配样机。",
    image: "/hardware/prototype.jpg",
    prompt:
      "Rapid prototype still, white SLA printed enclosure beside a CNC metal insert, calipers on a maker-lab table, soft overhead light, hardware academy commercial",
    duration: 6,
  },
  {
    id: "hw-ai-glasses",
    title: "AI 眼镜",
    tag: "AI 硬件",
    brand: "LENS PILOT",
    kind: "hardware",
    description: "镜腿传感器与鼻托微距，适合 AI 眼镜、AR 模组开场英雄镜。",
    image: "/hardware/wearable.jpg",
    prompt:
      "Premium AI smart glasses product hero, matte titanium temples, micro sensors at the hinge, cool daylight, clean electronics commercial, 16:9, no text",
    duration: 5,
  },
  {
    id: "hw-edge-box",
    title: "边缘推理盒",
    tag: "AI 硬件",
    brand: "EDGE FORGE",
    kind: "hardware",
    description: "铝合金散热壳体与接口特写，适合端侧推理盒、工控 AI 主机。",
    image: "/hardware/cnc-body.jpg",
    prompt:
      "Edge AI inference box, CNC aluminum chassis with heat vents and I/O ports, dark bench, cool workshop light, industrial electronics TVC, 16:9",
    duration: 5,
  },
  {
    id: "hw-robot-arm",
    title: "具身机器人工位",
    tag: "AI 硬件",
    brand: "SOMA LAB",
    kind: "hardware",
    description: "装配台与关节样机，适合具身机器人、协作臂科创片。",
    image: "/hardware/workshop.jpg",
    prompt:
      "Embodied robot workstation in a hardware academy, joint prototype and PCB on a clean bench, documentary-commercial lighting, 16:9, no text",
    duration: 8,
  },
];

export const HARDWARE_TAGS = ["结构件", "工坊", "板卡", "无人机", "可穿戴", "样机", "AI 硬件"] as const;

export const LOOKBOOK_PROMOS: BeautyPromo[] = [
  ...BEAUTY_PROMOS.map((p) => ({ ...p, kind: "beauty" as const })),
  ...HARDWARE_PROMOS,
];

export const LOOKBOOK_TAGS = ["全部", "美学", "硬件", ...BEAUTY_TAGS.slice(1), ...HARDWARE_TAGS] as const;
