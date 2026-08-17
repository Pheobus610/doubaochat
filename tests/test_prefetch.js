/**
 * 预生成状态机逻辑验证。
 * 把 app.js 里的 prefetch 相关函数抽出来单独跑，验证：
 *   - 不会重复发请求
 *   - 讲解重新生成后旧预取结果会被作废
 *   - 预取失败时静默降级，由正式流程兜底
 */
const assert = require("node:assert");

// ---- 复刻 app.js 中的预取实现（保持逻辑一致）----
const prefetch = {
  quiz: { status: "idle", data: null, error: null, promise: null, token: 0 },
};

function resetPrefetch(kind) {
  const slot = prefetch[kind];
  if (!slot) return;
  slot.token += 1;
  slot.status = "idle";
  slot.data = null;
  slot.error = null;
  slot.promise = null;
}

function startPrefetch(kind, fetcher) {
  const slot = prefetch[kind];
  if (!slot) return null;
  if (slot.status === "loading" || slot.status === "ready") return slot.promise;
  const myToken = slot.token;
  slot.status = "loading";
  slot.error = null;
  slot.promise = (async () => {
    try {
      const data = await fetcher();
      if (myToken !== slot.token) return null;
      slot.data = data;
      slot.status = "ready";
      return data;
    } catch (err) {
      if (myToken !== slot.token) return null;
      slot.error = err;
      slot.status = "error";
      return null;
    }
  })();
  return slot.promise;
}

async function consumePrefetch(kind) {
  const slot = prefetch[kind];
  if (!slot) return null;
  if (slot.status === "loading" && slot.promise) await slot.promise;
  if (slot.status === "ready" && slot.data) {
    const data = slot.data;
    slot.status = "idle";
    slot.data = null;
    slot.promise = null;
    return data;
  }
  return null;
}

// ---- 测试 ----
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("并发多次 startPrefetch 只发一次请求", async () => {
  resetPrefetch("quiz");
  let calls = 0;
  const fetcher = async () => {
    calls += 1;
    await new Promise((r) => setTimeout(r, 20));
    return { questions: [1, 2, 3] };
  };
  await Promise.all([
    startPrefetch("quiz", fetcher),
    startPrefetch("quiz", fetcher),
    startPrefetch("quiz", fetcher),
  ]);
  assert.strictEqual(calls, 1, `应只请求 1 次，实际 ${calls} 次`);
});

test("已 ready 后再次 startPrefetch 不重复请求", async () => {
  resetPrefetch("quiz");
  let calls = 0;
  const fetcher = async () => {
    calls += 1;
    return { questions: [1] };
  };
  await startPrefetch("quiz", fetcher);
  await startPrefetch("quiz", fetcher);
  assert.strictEqual(calls, 1);
});

test("consumePrefetch 命中后即失效，第二次返回 null", async () => {
  resetPrefetch("quiz");
  await startPrefetch("quiz", async () => ({ questions: [7] }));
  const first = await consumePrefetch("quiz");
  assert.deepStrictEqual(first, { questions: [7] });
  const second = await consumePrefetch("quiz");
  assert.strictEqual(second, null, "取走后应失效，避免重新生成时拿到旧数据");
});

test("consumePrefetch 会等待仍在飞行的请求", async () => {
  resetPrefetch("quiz");
  startPrefetch("quiz", async () => {
    await new Promise((r) => setTimeout(r, 30));
    return { questions: ["late"] };
  });
  const got = await consumePrefetch("quiz");
  assert.deepStrictEqual(got, { questions: ["late"] }, "应等待而非直接返回 null");
});

test("讲解重新生成 → reset 让旧预取结果作废", async () => {
  resetPrefetch("quiz");
  const inflight = startPrefetch("quiz", async () => {
    await new Promise((r) => setTimeout(r, 30));
    return { questions: ["stale"] };
  });
  resetPrefetch("quiz"); // 模拟用户重新生成讲解
  await inflight;
  assert.strictEqual(prefetch.quiz.status, "idle", "旧结果不应写入槽位");
  const got = await consumePrefetch("quiz");
  assert.strictEqual(got, null, "不应拿到基于旧讲解的题目");
});

test("预取失败静默降级，consume 返回 null 交给正式流程", async () => {
  resetPrefetch("quiz");
  await startPrefetch("quiz", async () => {
    throw new Error("模型超时");
  });
  assert.strictEqual(prefetch.quiz.status, "error");
  const got = await consumePrefetch("quiz");
  assert.strictEqual(got, null);
});

test("失败后可重新预取（error 状态不阻塞重试）", async () => {
  resetPrefetch("quiz");
  await startPrefetch("quiz", async () => {
    throw new Error("第一次失败");
  });
  let calls = 0;
  await startPrefetch("quiz", async () => {
    calls += 1;
    return { questions: ["retry ok"] };
  });
  assert.strictEqual(calls, 1, "error 状态应允许重试");
  assert.strictEqual(prefetch.quiz.status, "ready");
});

(async () => {
  let pass = 0;
  let fail = 0;
  for (const [name, fn] of tests) {
    try {
      await fn();
      console.log(`  ✅ ${name}`);
      pass += 1;
    } catch (err) {
      console.log(`  ❌ ${name}\n     ${err.message}`);
      fail += 1;
    }
  }
  console.log(`\n预生成状态机: ${pass} 通过, ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
