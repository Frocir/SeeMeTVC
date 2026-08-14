import { Link } from "react-router-dom";

export default function CharactersPage() {
  return (
    <section>
      <Link className="page-back" to="/">
        ← 工作区
      </Link>
      <div className="empty-panel">
        <p className="eyebrow">人物资产库</p>
        <h1>一级人物库本轮尚未开放</h1>
        <p className="lead">
          人物库本轮空着。请在项目里的 <strong>图片</strong> 节点上传肖像，或到左侧{" "}
          <strong>素材</strong> Tab 上传图片。
        </p>
      </div>
    </section>
  );
}
