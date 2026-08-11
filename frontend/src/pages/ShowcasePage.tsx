import BeautyPromoGallery from "../components/BeautyPromoGallery";

export default function ShowcasePage() {
  return (
    <section className="showcase-page">
      <div className="page-head">
        <p className="eyebrow">Lookbook</p>
        <h1>美妆 TVC 灵感库</h1>
        <p className="lead">
          唇妆、底妆、护肤等垂类成片灵感。点进工作室可一键套用镜头提示词；正式成片请到「作品」回看。
        </p>
      </div>
      <BeautyPromoGallery
        title="现成广告灵感"
        subtitle="按品类浏览；去工作室可一键套用对应镜头提示词"
      />
    </section>
  );
}
