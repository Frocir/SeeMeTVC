import BeautyPromoGallery from "../components/BeautyPromoGallery";

export default function ShowcasePage() {
  return (
    <section className="showcase-page">
      <div className="page-head">
        <p className="eyebrow">Lookbook</p>
        <h1>美妆 TVC 宣传素材库</h1>
        <p className="lead">
          汇集唇妆、底妆、护肤、香氛等面部美妆垂类成片灵感。当前为公开网络素材占位，后续可替换为品牌实拍片。
        </p>
      </div>
      <BeautyPromoGallery
        title="现成广告灵感"
        subtitle="按品类浏览；去工作室可一键套用对应镜头提示词"
      />
    </section>
  );
}
