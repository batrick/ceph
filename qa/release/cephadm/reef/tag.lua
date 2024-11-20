TEMPLATE = [[
meta:
- desc: setup ceph/reef TAG_VERSION

tasks:
- install:
    tag: TAG_VERSION
    exclude_packages:
      - ceph-volume
- print: "**** done install task..."
- cephadm:
    image: quay.io/ceph/ceph:TAG_VERSION
    roleless: true
    compiled_cephadm_branch: reef
    conf:
      osd:
        # set config option for which cls modules are allowed to be loaded / used
        osd_class_load_list: "*"
        osd_class_default_list: "*"
- print: "**** done end installing TAG_VERSION cephadm ..."
- cephadm.shell:
    host.a:
      - ceph config set mgr mgr/cephadm/use_repo_digest true --force
- print: "**** done cephadm.shell ceph config set mgr..."
- cephadm.shell:
    host.a:
      - ceph orch status
      - ceph orch ps
      - ceph orch ls
      - ceph orch host ls
      - ceph orch device ls
]]

local output = ceph.git.ls_remote('https://github.com/ceph/ceph.git', 'refs/tags/*')
for sha1, tag in output:gmatch("(%x+)%s+(%S+)") do
  log.debug('reef/tag.lua: %s (%s)', tag, sha1)
  local reef_v = tag:match("^refs/tags/(v18.2.%d+)$")
  if reef_v then
    log.info("reef/tag.lua: creating node: %s", reef_v)
    local node_path = ("%s.yaml"):format(reef_v)
    local node = graph.Node(node_path, myself.graph)
    local node_yaml = TEMPLATE:gsub("TAG_VERSION", reef_v)
    node.set_content(yaml.safe_load(node_yaml))
    myself.link_source_to_node(node)
    myself.link_node_to_sink(node)
  end
end
