// Diagnostic only: public pinned Detour + operator-owned mesh. No bundled assets.
// Native query shape: df09f8, cursor: df0f78; see navigation/runtime leaves.
// This is not a production simulation backend or an official-server oracle.
#include "DetourNavMesh.h"
#include "DetourNavMeshQuery.h"
#include "DetourAlloc.h"
#include "DetourCommon.h"
#include <fstream>
#include <memory>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>

#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C"
#endif
static thread_local std::string error;
static void read(std::istream& f, void* p, size_t n) {
    if (!f.read(static_cast<char*>(p), n)) throw std::runtime_error("truncated store");
}
static void checked(dtStatus s, const char* operation) {
    if (dtStatusFailed(s)) throw std::runtime_error(std::string(operation)+": status="+std::to_string(s));
}
#define check(operation) checked((operation), #operation)
struct World {
    dtNavMesh mesh;
    dtNavMeshQuery query;
    dtQueryFilter filter;
    World(const char* path) {
        static_assert(sizeof(dtNavMeshParams)==28 && sizeof(dtMeshHeader)==100 &&
                      sizeof(dtPoly)==32 && sizeof(dtLink)==12, "ABI mismatch");
        std::ifstream file(path, std::ios::binary);
        uint32_t count; dtNavMeshParams params;
        read(file, &count, 4); read(file, &params, sizeof(params));
        if (!count || count > 16384) throw std::runtime_error("tile count");
        check(mesh.init(&params));
        for (uint32_t i=0; i<count; ++i) {
            uint32_t ref, size; read(file,&ref,4); read(file,&size,4);
            if (size<100 || size>1048576) throw std::runtime_error("tile size");
            auto* data=static_cast<unsigned char*>(dtAlloc(size,DT_ALLOC_PERM));
            if (!data) throw std::runtime_error("allocation failed");
            try { read(file,data,size); check(mesh.addTile(data,size,DT_TILE_FREE_DATA,ref,nullptr)); }
            catch (...) { dtFree(data); throw; }
        }
        if (file.peek()!=std::char_traits<char>::eof()) throw std::runtime_error("trailing bytes");
        check(query.init(&mesh,2048));
        filter.setIncludeFlags(0xfffe); filter.setExcludeFlags(0);
    }
};
static int repair(dtPolyRef* corridor, int count, const dtPolyRef* visited, int nv) {
    int ci=-1,vi=-1;
    for(int i=count-1;i>=0;--i) {
        for(int j=nv-1;j>=0;--j) if(corridor[i]==visited[j]) {ci=i;vi=j;}
        if(ci>=0) break;
    }
    if(ci<0 || vi<0) return count;
    int prefix=nv-vi,old=dtMin(ci+1,count),tail=dtMin(dtMax(0,count-old),256-prefix);
    if(tail) std::memmove(corridor+prefix,corridor+old,tail*sizeof(dtPolyRef));
    for(int i=0;i<prefix;++i) corridor[i]=visited[nv-1-i];
    return prefix+tail;
}
API const char* hc_error() { return error.c_str(); }
API void* hc_open(const char* path) {
    try {error.clear();return new World(path);} catch(const std::exception& e) {error=e.what();return nullptr;}
}
API void hc_close(void* ptr) { delete static_cast<World*>(ptr); }
// Caller serializes use of a handle. Metadata: corridor count, ended flag,
// reached destination polygon, native128-point cap reached, height-query failures.
API int hc_path(void* ptr, const float* start, const float* end, float* out, int* meta) {
    try {
        error.clear(); if (!ptr||!start||!end||!out||!meta) throw std::runtime_error("null argument");
        for(int i=0;i<3;++i) if(!std::isfinite(start[i])||!std::isfinite(end[i])) throw std::runtime_error("nonfinite point");
        auto& w=*static_cast<World*>(ptr); auto& q=w.query;
        float extents[3]={1.5f,1.5f,1.5f}; dtPolyRef a=0,b=0,corridor[256]; int nc=0;
        check(q.findNearestPoly(start,extents,&w.filter,&a,nullptr));
        check(q.findNearestPoly(end,extents,&w.filter,&b,nullptr));
        if(!a||!b) throw std::runtime_error("nearest polygon absent");
        check(q.findPath(a,b,start,end,&w.filter,corridor,&nc,256));
        if(nc<1) throw std::runtime_error("no corridor");
        meta[0]=nc; meta[1]=0; meta[2]=(corridor[nc-1]==b); meta[3]=0; meta[4]=0;
        float current[3],goal[3];
        check(q.closestPointOnPolyBoundary(a,start,current));
        check(q.closestPointOnPolyBoundary(corridor[nc-1],end,goal));
        dtVcopy(out,current); int count=1;
        while(nc && count<128) {
            float straight[9]; unsigned char flags[3]; dtPolyRef refs[3]; int n=0;
            check(q.findStraightPath(current,goal,corridor,nc,straight,flags,refs,&n,3,0));
            int steer=0;
            while(steer<n) {
                float dx=straight[3*steer]-current[0],dz=straight[3*steer+2]-current[2];
                if((flags[steer]&4) || dx*dx+dz*dz>=.0001f || std::fabs(current[1]-straight[3*steer+1])>=1000) break;
                ++steer;
            }
            if(steer==n) break;
            if(flags[steer]&4) throw std::runtime_error("offmesh unsupported");
            bool ending=(flags[steer]&2)!=0;
            float target[3]={straight[3*steer],current[1],straight[3*steer+2]},delta[3];
            dtVsub(delta,target,current); float len=dtVlen(delta);
            if(len==0) throw std::runtime_error("zero steering vector");
            float scale=(ending&&len<1)?1:1/len,desired[3];dtVmad(desired,current,delta,scale);
            dtPolyRef visited[16];int nv=0;float next[3];
            check(q.moveAlongSurface(corridor[0],current,desired,&w.filter,next,visited,&nv,16));
            nc=repair(corridor,nc,visited,nv);
            // Native df09f8 initializes zero and ignores this status. Diagnostic only.
            float height=0;if(dtStatusFailed(q.getPolyHeight(corridor[0],next,&height))) ++meta[4];next[1]=height;
            float dx=target[0]-next[0],dz=target[2]-next[2];
            bool done=ending&&dx*dx+dz*dz<.0001f&&std::fabs(current[1]-height)<1;
            dtVcopy(current,done?goal:next);dtVcopy(out+3*count++,current);
            if(done) {meta[1]=1;break;}
        }
        meta[3]=count==128 && !meta[1];return count;
    } catch(const std::exception& e) {error=e.what();return -1;}
}
