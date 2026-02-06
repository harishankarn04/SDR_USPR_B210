find_package(PkgConfig)

PKG_CHECK_MODULES(PC_GR_PACKET_UTILS gnuradio-packet_utils)

FIND_PATH(
    GR_PACKET_UTILS_INCLUDE_DIRS
    NAMES gnuradio/packet_utils/api.h
    HINTS $ENV{PACKET_UTILS_DIR}/include
        ${PC_PACKET_UTILS_INCLUDEDIR}
    PATHS ${CMAKE_INSTALL_PREFIX}/include
          /usr/local/include
          /usr/include
)

FIND_LIBRARY(
    GR_PACKET_UTILS_LIBRARIES
    NAMES gnuradio-packet_utils
    HINTS $ENV{PACKET_UTILS_DIR}/lib
        ${PC_PACKET_UTILS_LIBDIR}
    PATHS ${CMAKE_INSTALL_PREFIX}/lib
          ${CMAKE_INSTALL_PREFIX}/lib64
          /usr/local/lib
          /usr/local/lib64
          /usr/lib
          /usr/lib64
          )

include("${CMAKE_CURRENT_LIST_DIR}/gnuradio-packet_utilsTarget.cmake")

INCLUDE(FindPackageHandleStandardArgs)
FIND_PACKAGE_HANDLE_STANDARD_ARGS(GR_PACKET_UTILS DEFAULT_MSG GR_PACKET_UTILS_LIBRARIES GR_PACKET_UTILS_INCLUDE_DIRS)
MARK_AS_ADVANCED(GR_PACKET_UTILS_LIBRARIES GR_PACKET_UTILS_INCLUDE_DIRS)
