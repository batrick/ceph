if(WITH_LIBCEPHSQLITE)
  add_executable(unittest_libcephsqlite
    unittest_libcephsqlite.cc
  )
  target_link_libraries(unittest_libcephsqlite
    cephsqlite
    librados
    ceph-common
    ${SQLITE3_LIBRARIES}
    ${UNITTEST_LIBS}
    ${EXTRALIBS}
    ${CMAKE_DL_LIBS}
    )
  install(TARGETS unittest_libcephsqlite
    DESTINATION ${CMAKE_INSTALL_BINDIR})
endif(WITH_LIBCEPHSQLITE)
