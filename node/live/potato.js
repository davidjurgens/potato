function T(d) {
  return d && d.__esModule && Object.prototype.hasOwnProperty.call(d, "default") ? d.default : d;
}
var y = { exports: {} }, C = { exports: {} }, R;
function H() {
  return R || (R = 1, (function(d, _) {
    (function(n) {
      _ = n(), d.exports = _;
    })(function() {
      var n = function(e) {
        return e instanceof Function;
      }, r = function(e) {
        var i = Array.prototype.slice.call(arguments, 1);
        for (var o in i) {
          var a = i[o];
          if (typeof a == "object")
            for (var h in a)
              e[h] = a[h];
        }
        return e;
      }, s = {
        // internal object for indicating that class objects don't have a class object themselves,
        // may not be used by users
        _isClassObject: !1
      }, l = !1, t = function() {
      };
      return t._subClasses = [], t.prototype.init = function() {
      }, t._extend = function(e, i, o) {
        e === void 0 && (e = {}), i === void 0 && (i = {}), o === void 0 && (o = {}), o = r({}, s, o);
        var a = function() {
          l || (this._class = a, this.init instanceof Function && this.init.apply(this, arguments));
        }, h = this;
        l = !0;
        var u = new h();
        l = !1;
        var c = h.prototype;
        a.prototype = u, a.prototype.constructor = a, a._superClass = h, a._subClasses = [], h._subClasses.push(a), a._extend = h._extend, a._extends = function(O) {
          return this._superClass == t ? !1 : O == this._superClass || O == t ? !0 : this._superClass._extends(O);
        };
        for (var f in e) {
          var p = Object.getOwnPropertyDescriptor(e, f), x = p.value;
          if (x !== null && typeof x == "object" && x.descriptor)
            Object.defineProperty(u, f, x);
          else if (!("value" in p) && ("set" in p || "get" in p))
            Object.defineProperty(u, f, p);
          else {
            u[f] = x;
            var A = c[f];
            n(x) && n(A) && x !== A && (x._super = A);
          }
        }
        if (!o._isClassObject) {
          var m = h._members === void 0 ? t : h._members._class, g = r({}, o, { _isClassObject: !0 }), v = m._extend(i, {}, g);
          v._instanceClass = a, a._members = new v();
        }
        return a;
      }, t._convert = function(e, i) {
        var o = e.prototype;
        return o.init = function() {
          var a = this._origin = t._construct(e, arguments);
          Object.keys(a).forEach(function(h) {
            a.hasOwnProperty(h) && Object.defineProperty(this, h, {
              get: function() {
                return a[h];
              }
            });
          }, this);
        }, t._extend(o, {}, i);
      }, t._construct = function(e, i) {
        i === void 0 && (i = []);
        var o = function() {
          return e.apply(this, i);
        };
        return o.prototype = e.prototype, new o();
      }, t._superDescriptor = function(e, i) {
        if ("_class" in e && e instanceof e._class && (e = e._class), "_extends" in e && e._extends instanceof Function && e._extends(this))
          return Object.getOwnPropertyDescriptor(e._superClass.prototype, i);
      }, t;
    });
  })(C, C.exports)), C.exports;
}
var E, b;
function I() {
  if (b) return E;
  b = 1;
  var d = H(), _ = d._extend({
    //-----------------------------------
    // Constructor
    //-----------------------------------
    init: function(n, r, s) {
      n = n instanceof Array ? n : [n], this._map = {}, this._list = [], this.callback = r, this.keyFields = n, this.isHashArray = !0, this.options = s || {
        ignoreDuplicates: !1
      }, r && r("construct");
    },
    //-----------------------------------
    // add()
    //-----------------------------------
    addOne: function(n) {
      var r = !1;
      for (var s in this.keyFields) {
        s = this.keyFields[s];
        var l = this.objectAt(n, s);
        if (l)
          if (this.has(l)) {
            if (this.options.ignoreDuplicates)
              return;
            if (this._map[l].indexOf(n) != -1) {
              r = !0;
              continue;
            }
            this._map[l].push(n);
          } else this._map[l] = [n];
      }
      (!r || this._list.indexOf(n) == -1) && this._list.push(n);
    },
    add: function() {
      for (var n = 0; n < arguments.length; n++)
        this.addOne(arguments[n]);
      return this.callback && this.callback("add", Array.prototype.slice.call(arguments, 0)), this;
    },
    addAll: function(n) {
      if (n.length < 100)
        this.add.apply(this, n);
      else
        for (var r = 0; r < n.length; r++)
          this.add(n[r]);
      return this;
    },
    addMap: function(n, r) {
      return this._map[n] = r, this.callback && this.callback("addMap", {
        key: n,
        obj: r
      }), this;
    },
    //-----------------------------------
    // Intersection, union, etc.
    //-----------------------------------
    /**
     * Returns a new HashArray that contains the intersection between this (A) and the hasharray passed in (B). Returns A ^ B.
     */
    intersection: function(n) {
      var r = this;
      if (!n || !n.isHashArray)
        throw Error("Cannot HashArray.intersection() on a non-hasharray object. You passed in: ", n);
      var s = this.clone(null, !0), l = this.clone(null, !0).addAll(this.all.concat(n.all));
      return l.all.forEach(function(t) {
        r.collides(t) && n.collides(t) && s.add(t);
      }), s;
    },
    /**
     * Returns a new HashArray that contains the complement (difference) between this hash array (A) and the hasharray passed in (B). Returns A - B.
     */
    complement: function(n) {
      if (!n || !n.isHashArray)
        throw Error("Cannot HashArray.complement() on a non-hasharray object. You passed in: ", n);
      var r = this.clone(null, !0);
      return this.all.forEach(function(s) {
        n.collides(s) || r.add(s);
      }), r;
    },
    //-----------------------------------
    // Retrieval
    //-----------------------------------
    get: function(n) {
      if (this.has(n))
        return !(this._map[n] instanceof Array) || this._map[n].length != 1 ? this._map[n] : this._map[n][0];
    },
    getAll: function(n) {
      if (n = n instanceof Array ? n : [n], n[0] == "*")
        return this.all;
      var r = new _(this.keyFields);
      for (var s in n)
        r.add.apply(r, this.getAsArray(n[s]));
      return r.all;
    },
    getAsArray: function(n) {
      return this._map[n] || [];
    },
    getUniqueRandomIntegers: function(n, r, s) {
      var l = [], t = {};
      for (n = Math.min(Math.max(s - r, 1), n); l.length < n; ) {
        var e = Math.floor(r + Math.random() * (s + 1));
        t[e] || (t[e] = !0, l.push(e));
      }
      return l;
    },
    sample: function(n, r) {
      var s = this.all, l = [];
      r && (s = this.getAll(r));
      for (var t = this.getUniqueRandomIntegers(n, 0, s.length - 1), e = 0; e < t.length; e++)
        l.push(s[t[e]]);
      return l;
    },
    //-----------------------------------
    // Peeking
    //-----------------------------------
    has: function(n) {
      return this._map.hasOwnProperty(n);
    },
    collides: function(n) {
      for (var r in this.keyFields)
        if (this.has(this.objectAt(n, this.keyFields[r])))
          return !0;
      return !1;
    },
    hasMultiple: function(n) {
      return this._map[n] instanceof Array;
    },
    //-----------------------------------
    // Removal
    //-----------------------------------
    removeByKey: function() {
      for (var n = [], r = 0; r < arguments.length; r++) {
        var s = arguments[r], l = this._map[s].concat();
        if (l) {
          n = n.concat(l);
          for (var t in l) {
            var e = l[t];
            for (var i in this.keyFields) {
              var o = this.objectAt(e, this.keyFields[i]);
              if (o && this.has(o)) {
                var i = this._map[o].indexOf(e);
                i != -1 && this._map[o].splice(i, 1), this._map[o].length == 0 && delete this._map[o];
              }
            }
            this._list.splice(this._list.indexOf(e), 1);
          }
        }
        delete this._map[s];
      }
      return this.callback && this.callback("removeByKey", n), this;
    },
    remove: function() {
      for (var n = 0; n < arguments.length; n++) {
        var r = arguments[n];
        for (var l in this.keyFields) {
          var s = this.objectAt(r, this.keyFields[l]);
          if (s) {
            var l = this._map[s].indexOf(r);
            if (l != -1)
              this._map[s].splice(l, 1);
            else
              throw new Error("HashArray: attempting to remove an object that was never added!" + s);
            this._map[s].length == 0 && delete this._map[s];
          }
        }
        var l = this._list.indexOf(r);
        if (l != -1)
          this._list.splice(l, 1);
        else
          throw new Error("HashArray: attempting to remove an object that was never added!" + s);
      }
      return this.callback && this.callback("remove", arguments), this;
    },
    removeAll: function() {
      var n = this._list.concat();
      return this._map = {}, this._list = [], this.callback && this.callback("remove", n), this;
    },
    //-----------------------------------
    // Utility
    //-----------------------------------
    objectAt: function(n, r) {
      if (typeof r == "string")
        return n[r];
      for (var s = r.concat(); s.length && n; )
        n = n[s.shift()];
      return n;
    },
    //-----------------------------------
    // Iteration
    //-----------------------------------
    forEach: function(n, r) {
      n = n instanceof Array ? n : [n];
      var s = this.getAll(n);
      return s.forEach(r), this;
    },
    forEachDeep: function(n, r, s) {
      n = n instanceof Array ? n : [n];
      var l = this, t = this.getAll(n);
      return t.forEach(function(e) {
        s(l.objectAt(e, r), e);
      }), this;
    },
    //-----------------------------------
    // Cloning
    //-----------------------------------
    clone: function(n, r) {
      var s = new _(this.keyFields.concat(), n || this.callback);
      return r || s.add.apply(s, this.all.concat()), s;
    },
    //-----------------------------------
    // Mathematical
    //-----------------------------------
    sum: function(n, r, s) {
      var l = this, t = 0;
      return this.forEachDeep(n, r, function(e, i) {
        s !== void 0 && (e *= l.objectAt(i, s)), t += e;
      }), t;
    },
    average: function(n, r, s) {
      var l = 0, t = 0, e = 0, i = this;
      return s !== void 0 && this.forEachDeep(n, s, function(o) {
        e += o;
      }), this.forEachDeep(n, r, function(o, a) {
        s !== void 0 && (o *= i.objectAt(a, s) / e), l += o, t++;
      }), s !== void 0 ? l : l / t;
    },
    //-----------------------------------
    // Filtering
    //-----------------------------------
    filter: function(n, r) {
      var s = this, l = typeof r == "function" ? r : e, t = new _(this.keyFields);
      return t.addAll(this.getAll(n).filter(l)), t;
      function e(i) {
        var o = s.objectAt(i, r);
        return o !== void 0 && o !== !1;
      }
    }
  });
  return Object.defineProperty(_.prototype, "all", {
    get: function() {
      return this._list;
    }
  }), Object.defineProperty(_.prototype, "map", {
    get: function() {
      return this._map;
    }
  }), E = _, typeof window < "u" && (window.HashArray = _), E;
}
var w, S;
function D() {
  return S || (S = 1, w = I()), w;
}
var j;
function q() {
  if (j) return y.exports;
  j = 1;
  var d = D(), _ = 64, n = /^[\s]*$/, r = [
    {
      regex: /[åäàáâãæ]/ig,
      alternate: "a"
    },
    {
      regex: /[èéêë]/ig,
      alternate: "e"
    },
    {
      regex: /[ìíîï]/ig,
      alternate: "i"
    },
    {
      regex: /[òóôõö]/ig,
      alternate: "o"
    },
    {
      regex: /[ùúûü]/ig,
      alternate: "u"
    },
    {
      regex: /[æ]/ig,
      alternate: "ae"
    }
  ];
  String.prototype.replaceCharAt = function(t, e) {
    return this.substr(0, t) + e + this.substr(t + e.length);
  };
  var s = function(t, e) {
    this.options = e || {}, this.options.ignoreCase = this.options.ignoreCase === void 0 ? !0 : this.options.ignoreCase, this.options.maxCacheSize = this.options.maxCacheSize || _, this.options.cache = this.options.hasOwnProperty("cache") ? this.options.cache : !0, this.options.splitOnRegEx = this.options.hasOwnProperty("splitOnRegEx") ? this.options.splitOnRegEx : /\s/g, this.options.splitOnGetRegEx = this.options.hasOwnProperty("splitOnGetRegEx") ? this.options.splitOnGetRegEx : this.options.splitOnRegEx, this.options.min = this.options.min || 1, this.options.keepAll = this.options.hasOwnProperty("keepAll") ? this.options.keepAll : !1, this.options.keepAllKey = this.options.hasOwnProperty("keepAllKey") ? this.options.keepAllKey : "id", this.options.idFieldOrFunction = this.options.hasOwnProperty("idFieldOrFunction") ? this.options.idFieldOrFunction : void 0, this.options.expandRegexes = this.options.expandRegexes || r, this.options.insertFullUnsplitKey = this.options.hasOwnProperty("insertFullUnsplitKey") ? this.options.insertFullUnsplitKey : !1, this.keyFields = t ? t instanceof Array ? t : [t] : [], this.root = {}, this.size = 0, this.options.cache && (this.getCache = new d("key"));
  };
  function l(t, e) {
    return e.length === 1 ? t[e[0]] : l(t[e[0]], e.slice(1, e.length));
  }
  return s.prototype = {
    add: function(t, e) {
      this.options.cache && this.clearCache(), typeof e == "number" && (e = void 0);
      var i = e || this.keyFields;
      for (var o in i) {
        var a = i[o], h = a instanceof Array, u = h ? l(t, a) : t[a];
        if (u) {
          u = u.toString();
          for (var c = this.expandString(u), f = 0; f < c.length; f++) {
            var p = c[f];
            this.map(p, t);
          }
        }
      }
    },
    /**
     * By default using the options.expandRegexes, given a string like 'ö är bra', this will expand it to:
     *
     * ['ö är bra', 'o är bra', 'ö ar bra', 'o ar bra']
     *
     * By default this was built to allow for internationalization, but it could be also be expanded to
     * allow for word alternates, etc. like spelling alternates ('teh' and 'the').
     *
     * This is used for insertion! This should not be used for lookup since if a person explicitly types
     * 'ä' they probably do not want to see all results for 'a'.
     *
     * @param value The string to find alternates for.
     * @returns {Array} Always returns an array even if no matches.
     */
    expandString: function(t) {
      var e = [t];
      if (this.options.expandRegexes && this.options.expandRegexes.length)
        for (var i = 0; i < this.options.expandRegexes.length; i++)
          for (var o = this.options.expandRegexes[i], a; (a = o.regex.exec(t)) !== null; ) {
            var h = t.replaceCharAt(a.index, o.alternate);
            e.push(h);
          }
      return e;
    },
    addAll: function(t, e) {
      for (var i = 0; i < t.length; i++)
        this.add(t[i], e);
    },
    reset: function() {
      this.root = {}, this.size = 0;
    },
    clearCache: function() {
      this.getCache = new d("key");
    },
    cleanCache: function() {
      for (; this.getCache.all.length > this.options.maxCacheSize; )
        this.getCache.remove(this.getCache.all[0]);
    },
    addFromObject: function(t, e) {
      this.options.cache && this.clearCache(), e = e || "value", this.keyFields.indexOf("_key_") == -1 && this.keyFields.push("_key_");
      for (var i in t) {
        var o = { _key_: i };
        o[e] = t[i], this.add(o);
      }
    },
    map: function(t, e) {
      if (this.options.splitOnRegEx && this.options.splitOnRegEx.test(t)) {
        var i = t.split(this.options.splitOnRegEx), o = i.filter(function(A) {
          return n.test(A);
        }), a = i.filter(function(A) {
          return A === t;
        }), h = a.length + o.length === i.length;
        if (!h) {
          for (var u = 0, c = i.length; u < c; u++)
            n.test(i[u]) || this.map(i[u], e);
          if (!this.options.insertFullUnsplitKey)
            return;
        }
      }
      this.options.cache && this.clearCache(), this.options.keepAll && (this.indexed = this.indexed || new d([this.options.keepAllKey]), this.indexed.add(e)), this.options.ignoreCase && (t = t.toLowerCase());
      var f = this.keyToArr(t), p = this;
      x(f, e, this.root);
      function x(A, m, g) {
        if (A.length == 0) {
          g.value = g.value || [], g.value.push(m);
          return;
        }
        var v = A.shift();
        g[v] || p.size++, g[v] = g[v] || {}, x(A, m, g[v]);
      }
    },
    keyToArr: function(t) {
      var e;
      if (this.options.min && this.options.min > 1) {
        if (t.length < this.options.min)
          return [];
        e = [t.substr(0, this.options.min)], e = e.concat(t.substr(this.options.min).split(""));
      } else e = t.split("");
      return e;
    },
    findNode: function(t) {
      return e(this.keyToArr(t), this.root);
      function e(i, o) {
        if (o) {
          if (i.length == 0) return o;
          var a = i.shift();
          return e(i, o[a]);
        }
      }
    },
    _getCacheKey: function(t, e) {
      var i = t;
      return e && (i = t + "_" + e), i;
    },
    _get: function(t, e) {
      t = this.options.ignoreCase ? t.toLowerCase() : t;
      var i, o;
      if (this.options.cache && (i = this.getCache.get(this._getCacheKey(t, e))))
        return i.value;
      for (var a = void 0, h = this.options.indexField ? [this.options.indexField] : this.keyFields, u = this.options.splitOnGetRegEx ? t.split(this.options.splitOnGetRegEx) : [t], c = 0, f = u.length; c < f; c++)
        if (!(this.options.min && u[c].length < this.options.min)) {
          var p = new d(h);
          (o = this.findNode(u[c])) && m(o, p), a = a ? a.intersection(p) : p;
        }
      var x = a ? a.all : [];
      if (this.options.cache) {
        var A = this._getCacheKey(t, e);
        this.getCache.add({ key: A, value: x }), this.cleanCache();
      }
      return x;
      function m(g, v) {
        if (!(e && v.all.length === e)) {
          if (g.value && g.value.length)
            if (!e || v.all.length + g.value.length < e)
              v.addAll(g.value);
            else {
              v.addAll(g.value.slice(0, e - v.all.length));
              return;
            }
          for (var O in g) {
            if (e && v.all.length === e)
              return;
            O != "value" && m(g[O], v);
          }
        }
      }
    },
    get: function(t, e, i) {
      var o = this.options.indexField ? [this.options.indexField] : this.keyFields, a = void 0, h = void 0;
      if (e && !this.options.idFieldOrFunction)
        throw new Error("To use the accumulator, you must specify and idFieldOrFunction");
      t = t instanceof Array ? t : [t];
      for (var u = 0, c = t.length; u < c; u++) {
        var f = this._get(t[u], i);
        e ? h = e(h, t[u], f, this) : a = a ? a.addAll(f) : new d(o).addAll(f);
      }
      return e ? h : a.all;
    },
    search: function(t, e, i) {
      return this.get(t, e, i);
    },
    getId: function(t) {
      return typeof this.options.idFieldOrFunction == "function" ? this.options.idFieldOrFunction(t) : t[this.options.idFieldOrFunction];
    }
  }, s.UNION_REDUCER = function(t, e, i, o) {
    if (t === void 0)
      return i;
    var a = {}, h, u, c = Math.max(t.length, i.length), f = [], p = 0;
    for (h = 0; h < c; h++)
      h < t.length && (u = o.getId(t[h]), a[u] = a[u] ? a[u] : 0, a[u]++, a[u] === 2 && (f[p++] = t[h])), h < i.length && (u = o.getId(i[h]), a[u] = a[u] ? a[u] : 0, a[u]++, a[u] === 2 && (f[p++] = i[h]));
    return f;
  }, y.exports = s, y.exports.default = s, y.exports;
}
var F, P;
function L() {
  return P || (P = 1, F = q()), F;
}
var N = L();
const U = /* @__PURE__ */ T(N);
(function() {
  function d(l) {
    const t = document.getElementById(l);
    if (t !== null)
      try {
        return JSON.parse(t.textContent);
      } catch (e) {
        console.warn(`could not parse json element '${l}'. Error: ${e}`);
      }
  }
  function _(l) {
    const t = document.getElementById("instance-text");
    if (t === null) {
      console.warn("cannot find instance text");
      return;
    }
    const e = t.textContent;
    if (!e || e === "") {
      console.log("text content in instance");
      return;
    }
    const i = new U(void 0, {
      splitOnRegEx: !1
    });
    l.map((c) => i.map(c, c));
    const o = e.split(" ");
    let a = !1, h = "", u = "";
    for (const c of o) {
      const f = h + c, p = i.search(f);
      if (p.length === 0 && a) {
        u += `
                <mark aria-hidden="true" class="emphasis">${h}</mark>
                `, u += c + " ", h = "", a = !1;
        continue;
      }
      if (p.length === 0) {
        u += c + " ", h = "";
        continue;
      }
      if (p.length === 1 && p[0] === f) {
        u += `
                <mark aria-hidden="true" class="emphasis">${f}</mark>
                `, h = "", a = !1;
        continue;
      }
      p.includes(f) && (a = !0), h = f + " ";
    }
    t.innerHTML = u;
  }
  function n(l) {
    try {
      for (const t of l) {
        const e = document.getElementById(t.name);
        if (e === null) {
          console.warn("no elem with id " + t.name);
          continue;
        }
        if (e.classList.contains("multiselect") || e.classList.contains("radio")) {
          const i = document.getElementById(t.name + ":::" + t.label);
          if (e === null) {
            console.warn(`no elem with id ${t.name + ":::" + t.label}`);
            continue;
          }
          i?.parentElement?.classList.add("suggestion");
        }
      }
    } catch {
      console.error("could not suggest elements");
    }
  }
  const r = d("emphasis");
  r !== void 0 && _(r);
  const s = d("suggestions");
  s !== void 0 && n(s);
})();
