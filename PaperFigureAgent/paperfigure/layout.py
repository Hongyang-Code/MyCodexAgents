"""Deterministic layered placement plus obstacle-aware orthogonal path search."""
import heapq
import math

PORTS = {'left':(0,.5), 'right':(1,.5), 'top':(.5,0), 'bottom':(.5,1)}


def port(box, side):
    u,v = PORTS[side]
    return (box['x']+u*box['w'], box['y']+v*box['h'])


def inside(p, box, pad=0):
    return box['x']-pad < p[0] < box['x']+box['w']+pad and box['y']-pad < p[1] < box['y']+box['h']+pad


def hits(a,b,box,pad=0):
    x,y,w,h = box['x']-pad,box['y']-pad,box['w']+2*pad,box['h']+2*pad
    if abs(a[0]-b[0]) < .01:
        return x < a[0] < x+w and max(min(a[1],b[1]),y) < min(max(a[1],b[1]),y+h)-.01
    if abs(a[1]-b[1]) < .01:
        return y < a[1] < y+h and max(min(a[0],b[0]),x) < min(max(a[0],b[0]),x+w)-.01
    # Conservative rejection for unsupported diagonal segments in orthogonal routing.
    return max(min(a[0],b[0]),x) < min(max(a[0],b[0]),x+w) and max(min(a[1],b[1]),y) < min(max(a[1],b[1]),y+h)


def crosses(a,b,c,d):
    def orient(p,q,r): return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return orient(a,b,c)*orient(a,b,d) < 0 and orient(c,d,a)*orient(c,d,b) < 0


def simplify(points):
    result=[]
    for p in points:
        p=tuple(p)
        if result and p==result[-1]: continue
        if len(result)>1 and ((result[-2][0]==result[-1][0]==p[0]) or (result[-2][1]==result[-1][1]==p[1])):
            result[-1]=p
        else: result.append(p)
    return result


def route(start,end,obstacles,used=()):
    """Visibility grid minimizes length, bends and prior-route crossings."""
    xs={start[0],end[0]}; ys={start[1],end[1]}
    for b in obstacles:
        xs.update([b['x']-20,b['x']+b['w']+20])
        ys.update([b['y']-20,b['y']+b['h']+20])
    xs=sorted(xs); ys=sorted(ys)
    points={(x,y) for x in xs for y in ys if not any(inside((x,y),b,8) for b in obstacles)}
    points.update((start,end))
    adjacency={p:[] for p in points}
    for axis,vals in ((0,xs),(1,ys)):
        for value in vals:
            line=sorted((p for p in points if p[axis]==value),key=lambda p:p[1-axis])
            for a,b in zip(line,line[1:]):
                if not any(hits(a,b,o,8) for o in obstacles):
                    adjacency[a].append(b);adjacency[b].append(a)
    initial=(start,'')
    distances={initial:0};previous={};queue=[(0,start,'')];finish=None
    while queue:
        cost,p,direction=heapq.heappop(queue)
        if cost!=distances.get((p,direction)):continue
        if p==end:finish=(p,direction);break
        for q in adjacency[p]:
            axis='v' if p[0]==q[0] else 'h'
            penalty=35 if direction and direction!=axis else 0
            penalty+=120*sum(crosses(p,q,a,b) for a,b in used)
            new=cost+abs(q[0]-p[0])+abs(q[1]-p[1])+penalty
            key=(q,axis)
            if new<distances.get(key,math.inf):
                distances[key]=new;previous[key]=(p,direction);heapq.heappush(queue,(new,q,axis))
    if finish is None:raise ValueError('No obstacle-free path; adjust spacing or ports, do not hide missing edge')
    result=[];key=finish
    while key!=initial:result.append(key[0]);key=previous[key]
    result.append(start)
    return simplify(reversed(result))


def place(graph, direction='LR'):
    nodes=graph['nodes'];ids={n['id'] for n in nodes};rank={i:0 for i in ids}
    forward=[e for e in graph['edges'] if not e.get('feedback') and e.get('kind')!='grouping']
    done=set()
    while len(done)<len(ids):
        ready=[i for i in sorted(ids-done) if all(e['source'] in done for e in forward if e['target']==i)]
        if not ready:raise ValueError('Cycle requires explicit feedback edge; do not silently delete dependencies')
        for i in ready:
            rank[i]=max([rank[e['source']]+1 for e in forward if e['target']==i]+[0]);done.add(i)
    ranks={r:[n for n in nodes if rank[n['id']]==r] for r in set(rank.values())}
    max_count=max(map(len,ranks.values()),default=1);boxes={}
    for r,items in ranks.items():
        for j,n in enumerate(items):
            x=60+r*255;y=100+(max_count-len(items))*75+j*150
            if direction=='TB':x,y=60+(max_count-len(items))*125+j*250,100+r*165
            boxes[n['id']]={'x':x,'y':y,'w':180,'h':74}
    return boxes


def plan(graph,direction='LR',boxes=None):
    boxes=boxes or place(graph,direction);edges={};used=[]
    groups={}
    node_map={n['id']:n for n in graph['nodes']}
    for group in graph.get('groups',[]):
        members=[boxes[n['id']] for n in graph['nodes'] if n.get('parent')==group['id']]
        if not members:continue
        x=min(b['x'] for b in members)-22;y=min(b['y'] for b in members)-38
        groups[group['id']]={'x':x,'y':y,'w':max(b['x']+b['w'] for b in members)-x+22,'h':max(b['y']+b['h'] for b in members)-y+22}
    for e in sorted(graph['edges'],key=lambda e:bool(e.get('feedback'))):
        a,b=boxes[e['source']],boxes[e['target']]
        if e.get('feedback'):s=t='bottom' if direction=='LR' else 'right'
        elif direction=='LR':s,t='right','left'
        else:s,t='bottom','top'
        s=e.get('source_port',s);t=e.get('target_port',t)
        start,end=port(a,s),port(b,t)
        # Include endpoints as obstacles after adding short outward stubs.
        def stub(p,side):
            dx,dy={'left':(-18,0),'right':(18,0),'top':(0,-18),'bottom':(0,18)}[side]
            return p[0]+dx,p[1]+dy
        related={node_map[e['source']].get('parent'),node_map[e['target']].get('parent')}
        obstacles=list(boxes.values())+[b for ident,b in groups.items() if ident not in related]
        middle=route(stub(start,s),stub(end,t),obstacles,used)
        points=simplify([start,*middle,end]);used.extend(zip(points,points[1:]))
        edges[e['id']]={'source_port':s,'target_port':t,'points':points,'label_offset':(22 if e.get('feedback') and direction=='LR' else -14),
                        'route_reason':'obstacle/feedback avoidance' if len(points)>3 else 'direct or one bend'}
    length=sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in used)
    bends=sum(max(0,len(e['points'])-2) for e in edges.values())
    crossings=sum(crosses(a,b,c,d) for i,(a,b) in enumerate(used) for c,d in used[i+1:])
    return {'direction':direction,'nodes':boxes,'edges':edges,'metrics':{'length':length,'bends':bends,'crossings':crossings},'score':length+35*bends+120*crossings}
