TEMPLATE = [[
meta:
- desc: install ceph/reef TAG_VERSION
tasks:
- install:
    tag: TAG_VERSION
    exclude_packages:
      - cephadm
      - ceph-mgr-cephadm
      - ceph-immutable-object-cache
      - python3-rados
      - python3-rgw
      - python3-rbd
      - python3-cephfs
      - ceph-volume
    extra_packages:
      - python-rados
      - python-rgw
      - python-rbd
      - python-cephfs
    # For kernel_untar_build workunit
    extra_system_packages:
      - bison
      - flex
      - elfutils-libelf-devel
      - openssl-devel
      - NetworkManager
      - iproute
      - util-linux
- print: "**** done installing TAG_VERSION"
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
      - ceph osd set-require-min-compat-client reef
- print: "**** done ceph"
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
