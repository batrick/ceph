TEMPLATE = [[
meta:
- desc: install ceph/squid TAG_VERSION
tasks:
- install:
    tag: TAG_VERSION
    exclude_packages:
      - librados3
      - ceph-mgr-dashboard
      - ceph-mgr-diskprediction-local
      - ceph-mgr-rook
      - ceph-mgr-cephadm
      - cephadm
      - ceph-volume
    extra_packages: ['librados2']
- print: "**** done installing squid TAG_VERSION"
- ceph:
    log-ignorelist:
      - overall HEALTH_
      - \(FS_
      - \(MDS_
      - \(OSD_
      - \(MON_DOWN\)
      - \(CACHE_POOL_
      - \(POOL_
      - \(MGR_DOWN\)
      - \(PG_
      - \(SMALLER_PGP_NUM\)
      - Monitor daemon marked osd
      - Behind on trimming
      - Manager daemon
    conf:
      global:
        mon warn on pool no app: false
        ms bind msgr2: false
- exec:
    osd.0:
      - ceph osd set-require-min-compat-client squid
- print: "**** done ceph"
]]

local output = ceph.git.ls_remote('https://github.com/ceph/ceph.git', 'refs/tags/*')
for sha1, tag in output:gmatch("(%x+)%s+(%S+)") do
  log.debug('squid/tag.lua: %s (%s)', tag, sha1)
  local squid_v = tag:match("^refs/tags/(v19.2.%d+)$")
  if squid_v then
    log.debug("squid/tag.lua: creating node: %s", squid_v)
    local node_path = ("%s.yaml"):format(squid_v)
    local node = graph.Node(node_path, myself.graph)
    node_yaml = TEMPLATE:gsub("TAG_VERSION", squid_v)
    node.set_content(yaml.safe_load(node_yaml))
    myself.link_source_to_node(node)
    myself.link_node_to_sink(node)
  end
end
